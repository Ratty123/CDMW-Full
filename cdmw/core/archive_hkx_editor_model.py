from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    'Optional',
    'Sequence',
    '_hkx_editor_add_body_rows',
    '_hkx_editor_add_constraint_rows',
    '_hkx_editor_add_object_rows',
    '_hkx_editor_add_raw_rows',
    '_hkx_editor_add_shape_rows',
    '_hkx_editor_add_tuning_rows',
    '_hkx_editor_build_context',
    '_hkx_editor_group_title',
)
def _hkx_editor_model_document(
    shapes: Sequence[Mapping[str, object]],
    physics_tuning: Optional[Mapping[str, object]],
    physics_body_summary: Optional[Mapping[str, object]],
    physics_constraint_summary: Optional[Mapping[str, object]],
    editable_field_catalog: Optional[Mapping[str, object]],
    byte_patch_map: Optional[Mapping[str, object]],
    objects: Sequence[Mapping[str, object]],
    advanced_payloads: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    (
        group_order,
        rows_by_group,
        patch_entries_by_shape_field,
        body_record_shape_links,
        body_context_by_shape_index,
    ) = _hkx_editor_build_context(shapes, byte_patch_map, objects, physics_body_summary)
    _hkx_editor_add_body_rows(rows_by_group, physics_body_summary, body_context_by_shape_index)
    _hkx_editor_add_shape_rows(rows_by_group, shapes, patch_entries_by_shape_field, body_context_by_shape_index)
    _hkx_editor_add_constraint_rows(rows_by_group, physics_constraint_summary)
    _hkx_editor_add_tuning_rows(rows_by_group, physics_tuning, body_record_shape_links, body_context_by_shape_index)
    _hkx_editor_add_object_rows(rows_by_group, objects)
    _hkx_editor_add_raw_rows(rows_by_group, advanced_payloads)
    groups = [
        {
            "key": group,
            "title": _hkx_editor_group_title(group),
            "row_count": len(rows_by_group[group]),
            "importable_row_count": sum(1 for row in rows_by_group[group] if bool(row.get("importable"))),
            "rows": rows_by_group[group],
        }
        for group in group_order
        if rows_by_group[group]
    ]
    importable_count = sum(int(group["importable_row_count"]) for group in groups)
    return {
        "status": "generated_from_current_decoder",
        "imported": False,
        "description": (
            "UI-ready HKX editor model. Rows are grouped for the guided workspace and are ignored on import; "
            "actual writes are validated against shapes, physics_tuning, advanced payloads, and byte lengths."
        ),
        "group_count": len(groups),
        "row_count": sum(int(group["row_count"]) for group in groups),
        "importable_row_count": importable_count,
        "groups": groups,
    }
