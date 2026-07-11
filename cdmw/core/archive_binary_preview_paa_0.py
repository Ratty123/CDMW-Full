from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
    'PurePosixPath',
)
def _paa_metabin_animation_stem(virtual_path: str) -> str:
    basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name
    lowered = basename.lower()
    if lowered.endswith(".paa_metabin"):
        return basename[: -len(".paa_metabin")]
    return PurePosixPath(basename).stem


@bind_binary_preview_globals(
    '_extract_binary_string_records',
    '_looks_like_structured_field_name',
    'struct',
)
def _paa_metabin_declared_type_name(data: bytes) -> Tuple[str, int, int]:
    if len(data) >= 0x18:
        name_length = struct.unpack_from("<I", data, 0x14)[0]
        if 0 < name_length <= 128 and 0x18 + name_length <= len(data):
            raw_name = data[0x18 : 0x18 + name_length]
            try:
                type_name = raw_name.decode("ascii", errors="strict").strip("\x00")
            except UnicodeDecodeError:
                type_name = ""
            if type_name and _looks_like_structured_field_name(type_name):
                return type_name, 0x18, int(name_length)
    for record in _extract_binary_string_records(data, sample_limit=4096, max_strings=16):
        if record.text == "AnimationMetaData":
            return record.text, record.offset, len(record.text)
    return "", 0, 0


@bind_binary_preview_globals(
    '_PAA_METABIN_TOKEN_HINTS',
    '_paa_metabin_animation_stem',
    're',
)
def _paa_metabin_filename_hint_rows(virtual_path: str) -> List[Dict[str, str]]:
    stem = _paa_metabin_animation_stem(virtual_path)
    tokens = [token for token in re.split(r"[_\-.]+", stem.lower()) if token]
    rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str, str]] = set()

    def add(kind: str, token: str, meaning: str, confidence: str = "filename_token") -> None:
        key = (kind, token, meaning)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "kind": kind,
                "token": token,
                "meaning": meaning,
                "confidence": confidence,
            }
        )

    if tokens and tokens[0] == "cd":
        add("Namespace", "cd", "Crimson Desert asset prefix", "filename_convention")
    if len(tokens) >= 2:
        add("Asset code", tokens[1], "character/object/sequence code from filename", "filename_token")
    for token in tokens:
        hint = _PAA_METABIN_TOKEN_HINTS.get(token)
        if hint is None:
            continue
        add(hint[0], token, hint[1])
    if stem:
        add("Animation stem", stem, "same-stem key used to find related animation files", "same_stem_relation_key")
    return rows


@bind_binary_preview_globals(
    'struct',
)
def _paa_metabin_header_rows(data: bytes) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if len(data) >= 4:
        rows.append(
            {
                "offset": 0,
                "name": "signature_words",
                "value": f"u16[0]=0x{struct.unpack_from('<H', data, 0)[0]:04X}, u16[1]={struct.unpack_from('<H', data, 2)[0]}",
                "confidence": "stable_in_corpus",
            }
        )
    if len(data) >= 0x18:
        rows.append(
            {
                "offset": 0x14,
                "name": "declared_type_name_length",
                "value": int(struct.unpack_from("<I", data, 0x14)[0]),
                "confidence": "stable_length_prefixed_string",
            }
        )
    for offset, label in ((0x2C, "descriptor_a"), (0x30, "descriptor_b"), (0x38, "descriptor_c"), (0x44, "descriptor_count")):
        if len(data) < offset + 4:
            continue
        be_value = struct.unpack_from(">I", data, offset)[0]
        le_value = struct.unpack_from("<I", data, offset)[0]
        plausible_value = be_value if be_value <= 1_000_000 else le_value
        rows.append(
            {
                "offset": offset,
                "name": label,
                "value": plausible_value,
                "be_u32": be_value,
                "le_u32": le_value,
                "confidence": "stable_descriptor_word_observed",
            }
        )
    return rows


@bind_binary_preview_globals(
)
def _paa_metabin_packed_stream_summary(data: bytes) -> Dict[str, object]:
    stream_offset = 0x50 if len(data) > 0x50 else len(data)
    stream = data[stream_offset:]
    marker_counts = {
        f"0x{marker:02X}": int(stream.count(marker))
        for marker in (0x00, 0x01, 0x05, 0x3C, 0x80, 0xFF)
        if stream.count(marker)
    }
    preview_rows: List[Dict[str, object]] = []
    for offset in range(stream_offset, min(len(data), stream_offset + 96), 8):
        chunk = data[offset : min(len(data), offset + 8)]
        if not chunk:
            continue
        preview_rows.append(
            {
                "offset": offset,
                "hex": chunk.hex(" ").upper(),
                "u16_le": [
                    int.from_bytes(chunk[index : index + 2], "little")
                    for index in range(0, len(chunk) - 1, 2)
                ],
                "u16_be": [
                    int.from_bytes(chunk[index : index + 2], "big")
                    for index in range(0, len(chunk) - 1, 2)
                ],
                "confidence": "packed_stream_preview",
            }
        )
    return {
        "stream_offset": stream_offset,
        "stream_size": len(stream),
        "marker_counts": marker_counts,
        "preview_rows": preview_rows,
        "status": "packed_event_or_timing_stream_observed" if stream else "no_metadata_stream_bytes",
        "confidence": "stable_header_plus_experimental_payload",
    }


@bind_binary_preview_globals(
    '_paa_metabin_animation_stem',
    '_paa_metabin_declared_type_name',
    '_paa_metabin_filename_hint_rows',
    '_paa_metabin_header_rows',
    '_paa_metabin_packed_stream_summary',
)
def _paa_metabin_analysis_document(data: bytes, virtual_path: str) -> Dict[str, object]:
    type_name, type_offset, type_length = _paa_metabin_declared_type_name(data)
    filename_hints = _paa_metabin_filename_hint_rows(virtual_path)
    stream_summary = _paa_metabin_packed_stream_summary(data)
    return {
        "declared_type": type_name or "unknown",
        "declared_type_offset": type_offset,
        "declared_type_length": type_length,
        "animation_stem": _paa_metabin_animation_stem(virtual_path),
        "filename_hints": filename_hints,
        "header_rows": _paa_metabin_header_rows(data),
        "packed_metadata_stream": stream_summary,
        "editing_supported": False,
        "relationship_use": (
            "Useful for linking animation metadata to same-stem .paa/.motionblending/.hkx style animation assets "
            "and for exposing filename-derived motion hints. The packed stream is not editable."
        ),
    }


@bind_binary_preview_globals(
    '_BinarySidecarStringRecord',
    '_PRINTABLE_BINARY_STRING_RE',
)
def _extract_binary_string_records(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_strings: int = 512,
) -> List[_BinarySidecarStringRecord]:
    sample = data[:sample_limit]
    records: List[_BinarySidecarStringRecord] = []
    seen: set[str] = set()
    for match in _PRINTABLE_BINARY_STRING_RE.finditer(sample):
        text = match.group().decode("ascii", errors="ignore").strip()
        letter_count = sum(1 for char in text if char.isalpha())
        if len(text) < 4 or text in seen or letter_count == 0:
            continue
        allowed_char_count = sum(1 for char in text if char.isalnum() or char in " _./:-[](){}")
        if allowed_char_count / max(len(text), 1) < 0.85:
            continue
        if len(text) < 12 and letter_count < 4:
            continue
        if "_" not in text and "/" not in text and "::" not in text and " " not in text and len(text) < 12:
            continue
        if len(text) > 240:
            text = text[:237] + "..."
        seen.add(text)
        records.append(_BinarySidecarStringRecord(offset=match.start(), text=text))
        if len(records) >= max_strings:
            break
    return records


@bind_binary_preview_globals(
    '_PRINTABLE_BINARY_STRING_RE',
)
def _read_binary_sidecar_string_at(data: bytes, offset: int, *, limit: int = 96) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    match = _PRINTABLE_BINARY_STRING_RE.match(data[offset : min(len(data), offset + limit)])
    if match is None:
        return ""
    text = match.group().decode("ascii", errors="ignore").strip()
    if not text or sum(1 for char in text if char.isalpha()) == 0:
        return ""
    if len(text) > 96:
        text = text[:93] + "..."
    return text


@bind_binary_preview_globals(
    'PurePosixPath',
    '_STRUCTURED_BINARY_ASSET_TOKEN_RE',
    '_clean_structured_binary_asset_token',
    '_looks_like_structured_asset_reference',
    '_normalize_model_texture_reference',
)
def _binary_sidecar_asset_reference_rows(
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_references: int = 96,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[str] = set()
    for record in string_records:
        for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(record.text):
            raw_text = _clean_structured_binary_asset_token(match.group(0))
            if not _looks_like_structured_asset_reference(raw_text):
                continue
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append(
                {
                    "offset": record.offset + match.start(),
                    "path": raw_text,
                    "extension": PurePosixPath(raw_text).suffix.lower(),
                    "confidence": "string_path",
                }
            )
            if len(rows) >= max_references:
                return rows
    return rows


@bind_binary_preview_globals(
    'struct',
)
def _binary_sidecar_header_words(data: bytes, *, max_words: int = 20) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for offset in range(0, min(len(data) // 4, max_words) * 4, 4):
        value = struct.unpack_from("<I", data, offset)[0]
        rows.append(
            {
                "offset": offset,
                "le_u32": value,
                "le_i32": struct.unpack_from("<i", data, offset)[0],
                "hex": f"0x{value:08X}",
            }
        )
    return rows


@bind_binary_preview_globals(
    'PurePosixPath',
    're',
)
def _seqmt_filename_grid_hint(virtual_path: str) -> Dict[str, object]:
    name = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name.lower()
    match = re.search(r"(?:^|_)(\d{1,3})x(\d{1,3})(?:_|\.|$)", name)
    if match is None:
        return {}
    return {
        "columns": int(match.group(1)),
        "rows": int(match.group(2)),
        "source": "filename_token",
    }
