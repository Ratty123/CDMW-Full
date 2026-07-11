from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_decode_gap_friendly_label',
    '_hkx_missing_decoder_requirements_for_type',
)
def _hkx_decoder_evidence_v2_document(
    summary: HkxTagfileSummary,
    converter_report: Mapping[str, object],
    native_backend: Mapping[str, object],
) -> Dict[str, object]:
    native_evidence = dict(summary.native_decoder_evidence_v2 or {})
    if native_evidence:
        class_statuses = [
            dict(row)
            for row in native_evidence.get("class_statuses", [])
            if isinstance(row, Mapping)
        ]
        fixup_backed_fields = [
            dict(row)
            for row in native_evidence.get("fixup_backed_fields", [])
            if isinstance(row, Mapping)
        ]
        return {
            "format": "cdmw_hkx_decoder_evidence_v2",
            "native_format": str(native_evidence.get("format") or ""),
            "status": str(native_evidence.get("status") or "read_only_native_evidence"),
            "source": "native_rust_cd_hkx",
            "imported": False,
            "read_only": True,
            "description": (
                "Normalized read-only HKX decoder evidence. It joins native fixup/PTCH semantics, graph links, "
                "owner-array context, and per-class decode gaps so the editor can show why something is linked."
            ),
            "reference_semantic_counts": dict(native_evidence.get("reference_semantic_counts") or {})
            if isinstance(native_evidence.get("reference_semantic_counts"), Mapping)
            else {},
            "link_evidence_counts": dict(native_evidence.get("link_evidence_counts") or {})
            if isinstance(native_evidence.get("link_evidence_counts"), Mapping)
            else {},
            "class_status_count": int(native_evidence.get("class_status_count") or len(class_statuses)),
            "priority_class_count": int(native_evidence.get("priority_class_count") or 0),
            "total_partial_byte_count": int(native_evidence.get("total_partial_byte_count") or 0),
            "unresolved_or_packed_case_count": int(native_evidence.get("unresolved_or_packed_case_count") or 0),
            "owner_array_count": int(native_evidence.get("owner_array_count") or native_backend.get("native_model_graph_owner_array_count") or 0),
            "class_statuses": class_statuses[:256],
            "truncated_class_status_count": max(0, len(class_statuses) - 256),
            "fixup_backed_fields": fixup_backed_fields[:256],
            "truncated_fixup_backed_field_count": max(0, len(fixup_backed_fields) - 256),
            "edit_policy": {
                "new_editable_fields_enabled": False,
                "allowed_edits": "existing fixed-size CDMW patch paths only",
                "blocked_edits": [
                    "mesh topology/count edits",
                    "reference edits",
                    "string edits",
                    "array count edits",
                    "Havok XML import",
                ],
            },
        }

    coverage_rows = converter_report.get("decode_coverage_by_type")
    class_statuses: List[Dict[str, object]] = []
    if isinstance(coverage_rows, list):
        for row in coverage_rows:
            if not isinstance(row, Mapping):
                continue
            type_name = str(row.get("type_name") or "")
            if not type_name:
                continue
            category, _reason, missing = _hkx_missing_decoder_requirements_for_type(type_name)
            status_counts = row.get("status_counts") if isinstance(row.get("status_counts"), Mapping) else {}
            status = (
                "raw_preserved"
                if int(status_counts.get("raw_preserved") or status_counts.get("raw") or 0)
                else "partially_decoded"
                if int(status_counts.get("partially_decoded") or 0)
                else "decoded"
            )
            class_statuses.append(
                {
                    "type_name": type_name,
                    "record_count": int(row.get("record_count") or 0),
                    "byte_count": int(row.get("byte_length") or 0),
                    "decoded_field_count": int(row.get("decoded_field_count") or 0),
                    "reference_count": int(row.get("reference_candidate_count") or 0),
                    "editable_field_count": int(row.get("editable_slot_count") or 0),
                    "status": status,
                    "friendly_status": _hkx_decode_gap_friendly_label(category, status),
                    "missing_requirements": missing,
                    "link_evidence": ["raw_observation"],
                    "corpus_priority_score": int(row.get("byte_length") or 0) + len(missing) * 256,
                    "read_only": True,
                }
            )
    class_statuses.sort(key=lambda row: (-int(row.get("corpus_priority_score") or 0), str(row.get("type_name") or "")))
    return {
        "format": "cdmw_hkx_decoder_evidence_v2",
        "native_format": "",
        "status": "python_synthetic_decoder_evidence",
        "source": "python_converter_report",
        "imported": False,
        "read_only": True,
        "description": "Synthetic read-only decoder evidence built from the Python converter report because native evidence was unavailable.",
        "reference_semantic_counts": {},
        "link_evidence_counts": {"raw_observation": len(class_statuses)} if class_statuses else {},
        "class_status_count": len(class_statuses),
        "priority_class_count": sum(1 for row in class_statuses if row.get("missing_requirements")),
        "total_partial_byte_count": sum(int(row.get("byte_count") or 0) for row in class_statuses),
        "unresolved_or_packed_case_count": 0,
        "owner_array_count": int(native_backend.get("native_model_graph_owner_array_count") or 0),
        "class_statuses": class_statuses[:256],
        "truncated_class_status_count": max(0, len(class_statuses) - 256),
        "fixup_backed_fields": [],
        "truncated_fixup_backed_field_count": 0,
        "edit_policy": {
            "new_editable_fields_enabled": False,
            "allowed_edits": "existing fixed-size CDMW patch paths only",
            "blocked_edits": ["Havok XML import", "reference edits", "array count edits"],
        },
    }


@bind_archive_hkx_globals()
def _hkx_raw_records_document(advanced_payloads: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    raw_records: List[Dict[str, object]] = []
    for payload_info in advanced_payloads:
        raw_records.append(
            {
                "record_index": payload_info.get("record_index"),
                "type_index": payload_info.get("type_index"),
                "type_name": payload_info.get("type_name"),
                "count": payload_info.get("count"),
                "byte_length": payload_info.get("byte_length"),
                "payload_hex": payload_info.get("payload_hex", ""),
                "edit_rule": "same_length_only",
                "status": "raw_preserved",
            }
        )
    return raw_records
