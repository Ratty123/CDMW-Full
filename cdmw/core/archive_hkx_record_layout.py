from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    'Optional',
    'Sequence',
    'Tuple',
    '_hkx_first_u32_words',
    '_hkx_layout_field',
    '_hkx_layout_field_byte_coverage',
    '_hkx_possible_record_link_documents',
    '_hkx_record_layout_fields_0',
    '_hkx_record_layout_fields_1',
    '_hkx_record_layout_fields_10',
    '_hkx_record_layout_fields_11',
    '_hkx_record_layout_fields_2',
    '_hkx_record_layout_fields_3',
    '_hkx_record_layout_fields_4',
    '_hkx_record_layout_fields_5',
    '_hkx_record_layout_fields_6',
    '_hkx_record_layout_fields_7',
    '_hkx_record_layout_fields_8',
    '_hkx_record_layout_fields_9',
    '_hkx_record_layout_post_0',
    '_hkx_record_layout_post_1',
    '_hkx_record_layout_post_2',
    '_hkx_record_layout_post_3',
    'math',
    'struct',
)
def _hkx_record_layout_document(
    payload: bytes,
    records: Sequence[HkxItemRecord],
    record: HkxItemRecord,
    *,
    offset_indexes: Optional[Tuple[Dict[int, Tuple[HkxItemRecord, ...]], Dict[int, Tuple[HkxItemRecord, ...]]]] = None,
) -> Dict[str, object]:
    stride = len(payload) // record.count if record.count else len(payload)
    fields: List[Dict[str, object]] = []
    type_name = record.type_name
    for decoder in (
        _hkx_record_layout_fields_0,
        _hkx_record_layout_fields_1,
        _hkx_record_layout_fields_2,
        _hkx_record_layout_fields_3,
        _hkx_record_layout_fields_4,
        _hkx_record_layout_fields_5,
        _hkx_record_layout_fields_6,
        _hkx_record_layout_fields_7,
        _hkx_record_layout_fields_8,
        _hkx_record_layout_fields_9,
        _hkx_record_layout_fields_10,
        _hkx_record_layout_fields_11,
    ):
        if decoder(payload, record, type_name, fields):
            break
    _hkx_record_layout_post_0(payload, record, type_name, fields, stride)
    _hkx_record_layout_post_1(payload, record, type_name, fields, stride)
    _hkx_record_layout_post_2(payload, record, type_name, fields, stride)
    _hkx_record_layout_post_3(payload, record, type_name, fields, stride)
    if type_name == "hknpBoxShape" and len(payload) >= 32:
        float_slots: List[Dict[str, object]] = []
        for offset in range(0, min(len(payload), 128) - 3, 4):
            value = struct.unpack_from("<f", payload, offset)[0]
            if math.isfinite(value) and 1e-8 <= abs(value) <= 1_000_000.0:
                float_slots.append({"offset": offset, "value": float(value)})
        fields.append(
            _hkx_layout_field(
                name="box_shape_payload_sample",
                offset=0,
                size=min(len(payload), 128),
                data_type="float32[]/uint32[]",
                value={"finite_float_slots": float_slots[:24], "u32_words": _hkx_first_u32_words(payload[:64], min(16, len(payload) // 4))},
                description=(
                    "Read-only hknpBoxShape payload sample. Box half-extents/orientation fields are not fully "
                    "named yet; convex-derived vertex/plane edits remain the safer path when present."
                ),
                confidence="experimental",
                editable=False,
            )
        )
    references = _hkx_possible_record_link_documents(payload, records, record, offset_indexes=offset_indexes)
    byte_coverage = _hkx_layout_field_byte_coverage(fields, len(payload))
    if fields:
        coverage_basis = (
            f"{len(fields)} layout field(s); "
            f"{byte_coverage['typed_byte_count']} typed byte(s), "
            f"{byte_coverage['candidate_byte_count']} candidate byte(s), "
            f"{byte_coverage['unresolved_byte_count']} unresolved byte(s)."
        )
    else:
        coverage_basis = "No typed layout fields are available; payload bytes are preserved as raw evidence."
    return {
        "status": "partial_layout" if fields else "raw_preserved",
        "stride": stride if record.count else None,
        "field_count": len(fields),
        "fields": fields[:512],
        "truncated_fields": max(0, len(fields) - 512),
        "references": references,
        "byte_coverage": byte_coverage,
        "coverage_basis": coverage_basis,
        "decode_source": "typed_layout" if any(str(field.get("decode_source") or "") == "typed_layout" for field in fields) else "raw_sample",
        "safe_edit_policy": "fixed_size_patch_only" if any(bool(field.get("editable")) for field in fields) else "read_only",
        "raw_preservation": {
            "offset": 0,
            "size": len(payload),
            "encoding": "hex",
            "edit_rule": "same_length_only",
            "description": "Original bytes are preserved exactly unless a supported fixed-size value edit is applied.",
        },
    }
