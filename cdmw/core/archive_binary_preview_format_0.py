from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
    '_seqmt_filename_grid_hint',
    'struct',
)
def _seqmt_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    max_frame_records: int = 96,
) -> Dict[str, object]:
    """Decode observed SEQMT DDS! sequence texture atlas metadata.

    Local corpus samples use an unaligned compact header:
    DDS!, version byte, u16 columns, u16 rows, one flag/packing byte, u16 frame count,
    then one four-byte record per frame. The four-byte record semantics are still
    read-only evidence, so expose multiple byte interpretations without naming a
    final value type.
    """

    if len(data) < 12 or data[:4] != b"DDS!":
        return {
            "recognized": False,
            "reason": "missing_DDS_sequence_magic",
            "editing_supported": False,
        }

    version = int(data[4])
    columns = int(struct.unpack_from("<H", data, 5)[0])
    rows = int(struct.unpack_from("<H", data, 7)[0])
    flags_or_packing = int(data[9])
    frame_count = int(struct.unpack_from("<H", data, 10)[0])
    payload_offset = 12
    frame_record_size = 4
    expected_frame_payload_bytes = frame_count * frame_record_size
    available_payload_bytes = max(0, len(data) - payload_offset)
    decoded_frame_bytes = min(available_payload_bytes, expected_frame_payload_bytes)
    decoded_frame_count = decoded_frame_bytes // frame_record_size
    trailing_payload_offset = payload_offset + expected_frame_payload_bytes
    trailing_payload_bytes = max(0, len(data) - trailing_payload_offset)
    grid_capacity = columns * rows
    filename_hint = _seqmt_filename_grid_hint(virtual_path)
    if filename_hint:
        filename_hint = dict(filename_hint)
        filename_hint["matches_header"] = (
            int(filename_hint.get("columns") or 0) == columns
            and int(filename_hint.get("rows") or 0) == rows
        )

    frame_records: List[Dict[str, object]] = []
    preview_count = min(decoded_frame_count, max_frame_records)
    for index in range(preview_count):
        offset = payload_offset + index * frame_record_size
        raw = data[offset : offset + frame_record_size]
        byte_values = [int(value) for value in raw]
        signed_values = [value - 256 if value >= 128 else value for value in byte_values]
        frame_records.append(
            {
                "index": index,
                "grid_x": index % columns if columns > 0 else 0,
                "grid_y": index // columns if columns > 0 else 0,
                "offset": offset,
                "hex": raw.hex(" ").upper(),
                "bytes_rgba": byte_values,
                "bytes_bgra": [byte_values[2], byte_values[1], byte_values[0], byte_values[3]]
                if len(byte_values) == 4
                else byte_values,
                "bytes_signed": signed_values,
            }
        )

    notes = [
        "Frame records are exposed as four raw bytes because the channel semantics are not proven yet.",
        "Editing is disabled until frame record meaning and rebuild rules are validated.",
    ]
    if flags_or_packing == 1:
        notes.append("The flag/packing byte is 1; local samples often use this on filenames containing 4pack.")
    if trailing_payload_bytes > 0:
        notes.append("Extra trailing payload was preserved separately from the fixed frame table.")

    return {
        "recognized": True,
        "format": "DDS_sequence_texture_metadata",
        "magic": "DDS!",
        "version": version,
        "columns": columns,
        "rows": rows,
        "grid_capacity": grid_capacity,
        "frame_count": frame_count,
        "frame_count_matches_grid": frame_count == grid_capacity,
        "flags_or_packing_byte": flags_or_packing,
        "payload_offset": payload_offset,
        "frame_record_size": frame_record_size,
        "expected_frame_payload_bytes": expected_frame_payload_bytes,
        "available_payload_bytes": available_payload_bytes,
        "decoded_frame_count": decoded_frame_count,
        "payload_complete": available_payload_bytes >= expected_frame_payload_bytes,
        "trailing_payload_offset": trailing_payload_offset if trailing_payload_bytes > 0 else None,
        "trailing_payload_bytes": trailing_payload_bytes,
        "trailing_payload_preview_hex": data[trailing_payload_offset : min(len(data), trailing_payload_offset + 64)].hex(" ").upper()
        if trailing_payload_bytes > 0
        else "",
        "filename_grid_hint": filename_hint,
        "frame_records_preview": frame_records,
        "frame_records_preview_truncated": decoded_frame_count > preview_count,
        "editing_supported": False,
        "confidence": "confirmed_on_local_seqmt_corpus_header",
        "notes": notes,
    }


@bind_binary_preview_globals(
    'struct',
)
def _paccd_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    max_rows: int = 24,
    max_row_bytes: int = 32,
) -> Dict[str, object]:
    """Decode observed PACCD character customization byte tables.

    Local corpus samples are either a compact 298-byte table or a larger
    palette-style table. Both variants share a small integer header where
    word 1 is consistently 14, followed by per-slot byte payloads. The byte
    semantics are not named yet, so expose row/byte evidence read-only.
    """

    if len(data) < 28:
        return {
            "recognized": False,
            "reason": "too_small_for_paccd_header",
            "editing_supported": False,
        }

    header_word_count = min(len(data) // 4, 8)
    header_words = [int(struct.unpack_from("<I", data, offset * 4)[0]) for offset in range(header_word_count)]
    slot_count = int(header_words[1]) if len(header_words) > 1 else 0
    profile_version = int(header_words[2]) if len(header_words) > 2 else 0
    if slot_count <= 0 or slot_count > 128:
        return {
            "recognized": False,
            "reason": "invalid_slot_count",
            "header_words_le_u32": header_words,
            "editing_supported": False,
        }

    candidate_offsets = (32, 28, 24)
    payload_offset = 32 if len(data) >= 32 else 28
    for candidate in candidate_offsets:
        if len(data) <= candidate:
            continue
        if (len(data) - candidate) % slot_count == 0:
            payload_offset = candidate
            break
    payload_size = max(0, len(data) - payload_offset)
    row_stride = payload_size // slot_count if slot_count > 0 else 0
    trailing_payload_bytes = payload_size - row_stride * slot_count
    format_family = "compact_customization_rows" if row_stride <= 32 else "extended_customization_palette"

    rows: List[Dict[str, object]] = []
    neutral_values = {0, 50, 100, 125, 255}
    for row_index in range(min(slot_count, max_rows)):
        row_offset = payload_offset + row_index * row_stride
        if row_offset >= len(data):
            break
        raw = data[row_offset : min(len(data), row_offset + row_stride)]
        byte_values = [int(value) for value in raw[:max_row_bytes]]
        if raw:
            minimum = min(int(value) for value in raw)
            maximum = max(int(value) for value in raw)
            non_zero_count = sum(1 for value in raw if int(value) != 0)
            non_neutral_count = sum(1 for value in raw if int(value) not in neutral_values)
        else:
            minimum = maximum = non_zero_count = non_neutral_count = 0
        rgb_candidates: List[Dict[str, object]] = []
        for component_offset in range(0, min(len(raw), max_row_bytes) - 2, 3):
            triplet = [int(raw[component_offset + index]) for index in range(3)]
            if triplet in ([0, 0, 0], [255, 255, 255]):
                continue
            rgb_candidates.append(
                {
                    "byte_offset_in_row": component_offset,
                    "rgb_bytes": triplet,
                    "normalized_rgb": [round(value / 255.0, 4) for value in triplet],
                }
            )
            if len(rgb_candidates) >= 4:
                break
        rows.append(
            {
                "slot_index": row_index,
                "offset": row_offset,
                "row_stride": row_stride,
                "preview_hex": raw[:max_row_bytes].hex(" ").upper(),
                "preview_bytes": byte_values,
                "min_byte": minimum,
                "max_byte": maximum,
                "non_zero_bytes": non_zero_count,
                "non_neutral_bytes": non_neutral_count,
                "rgb_candidates": rgb_candidates,
                "confidence": "observed_fixed_slot_byte_row",
            }
        )

    notes = [
        "PACCD row bytes are exposed as customization slider/palette evidence; exact field names are not proven.",
        "Editing is disabled until row ownership, defaults, and no-edit rebuilds are validated.",
    ]
    if row_stride == 19 and payload_offset == 32:
        notes.append("This matches the common 298-byte compact corpus layout: 32-byte header plus 14 x 19-byte rows.")
    elif row_stride > 32:
        notes.append("This looks like the extended customization palette layout with larger per-slot byte rows.")
    if trailing_payload_bytes:
        notes.append("Trailing bytes exist after the evenly divided slot rows and are preserved as unknown payload.")

    return {
        "recognized": True,
        "format": "character_customization_byte_table",
        "path_hint": str(virtual_path or ""),
        "header_words_le_u32": header_words,
        "slot_count": slot_count,
        "profile_version": profile_version,
        "payload_offset": payload_offset,
        "payload_size": payload_size,
        "row_stride": row_stride,
        "format_family": format_family,
        "trailing_payload_bytes": trailing_payload_bytes,
        "trailing_payload_preview_hex": data[
            payload_offset + row_stride * slot_count : min(len(data), payload_offset + row_stride * slot_count + 64)
        ].hex(" ").upper()
        if trailing_payload_bytes > 0
        else "",
        "rows_preview": rows,
        "rows_preview_truncated": slot_count > len(rows),
        "editing_supported": False,
        "confidence": "confirmed_on_local_paccd_corpus_header",
        "notes": notes,
    }
