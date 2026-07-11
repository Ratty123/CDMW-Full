from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_editor_model_preview_link_count(editor_model: object) -> int:
    if not isinstance(editor_model, Mapping):
        return 0
    count = 0
    groups = editor_model.get("groups")
    if not isinstance(groups, list):
        return 0
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        rows = group.get("rows")
        if not isinstance(rows, list):
            continue
        count += sum(
            1
            for row in rows
            if isinstance(row, Mapping) and str(row.get("viewer_selection_id") or "").strip()
        )
    return count


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_compatibility_status_from_counts',
    '_hkx_editor_model_preview_link_count',
)
def _hkx_compatibility_document(
    summary: HkxTagfileSummary,
    converter_report: Mapping[str, object],
    byte_patch_map: object,
    editor_model: object,
) -> Dict[str, object]:
    editable_target_count = 0
    if isinstance(byte_patch_map, Mapping):
        try:
            editable_target_count = int(byte_patch_map.get("entry_count") or 0)
        except (TypeError, ValueError, OverflowError):
            editable_target_count = 0
    if editable_target_count <= 0:
        try:
            editable_target_count = int(converter_report.get("editable_slot_count") or 0)
        except (TypeError, ValueError, OverflowError):
            editable_target_count = 0
    try:
        payload_record_count = int(converter_report.get("payload_record_count") or 0)
    except (TypeError, ValueError, OverflowError):
        payload_record_count = 0
    preview_linked_target_count = _hkx_editor_model_preview_link_count(editor_model)
    status = _hkx_compatibility_status_from_counts(
        sdk_version=summary.sdk_version,
        item_record_count=len(summary.item_records),
        payload_record_count=payload_record_count,
        size_matches=summary.size_matches,
        editable_target_count=editable_target_count,
        preview_linked_target_count=preview_linked_target_count,
    )
    return {
        "status": status,
        "status_scale": [
            "unsupported",
            "inspectable",
            "roundtrip_safe",
            "value_editable",
            "preview_linked",
        ],
        "description": (
            "CDMW Crimson Desert HKX compatibility classification for this export. "
            "Compatibility means CDMW JSON/XML preservation and fixed-size safe edits, not official Havok XML parity."
        ),
        "gates": {
            "sdkv20240200": summary.sdk_version == "20240200",
            "declared_size_matches_payload": summary.size_matches,
            "has_item_table": bool(summary.item_records),
            "payload_records_represented": payload_record_count,
            "item_record_count": len(summary.item_records),
            "unknown_bytes_preserved": payload_record_count >= len(summary.item_records) if summary.item_records else False,
            "editable_patch_targets": editable_target_count,
            "preview_linked_targets": preview_linked_target_count,
        },
        "unsupported_edits": [
            "changing record counts",
            "changing array lengths",
            "changing object references",
            "changing raw payload byte lengths",
            "adding/removing topology",
            "non-finite numeric values",
        ],
    }
