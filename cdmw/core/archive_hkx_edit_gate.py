from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxItemRecord',
    'List',
    'Mapping',
    'Optional',
    'Sequence',
    '_hkx_add_shape_patch_entries',
    '_hkx_add_tuning_patch_entries',
)
def _hkx_byte_patch_map_document(
    data: bytes,
    shapes: Sequence[Mapping[str, object]],
    physics_tuning: Optional[Mapping[str, object]],
    records: Sequence[HkxItemRecord],
) -> Optional[Dict[str, object]]:
    records_by_index = {record.index: record for record in records}
    entries: List[Dict[str, object]] = []
    component_offsets3 = {"x": 0, "y": 4, "z": 8}
    component_offsets4 = {"x": 0, "y": 4, "z": 8, "w": 12}
    plane_offsets = {"normal_x": 0, "normal_y": 4, "normal_z": 8, "distance": 12}
    _hkx_add_shape_patch_entries(data, entries, shapes, records_by_index, component_offsets3, component_offsets4, plane_offsets)
    _hkx_add_tuning_patch_entries(data, entries, physics_tuning, records_by_index)
    if not entries:
        return None
    return {
        "status": "generated_from_current_decoder",
        "imported": False,
        "entry_count": len(entries),
        "description": (
            "Byte-level patch map for fixed-size editable values. This is read-only converter metadata; "
            "the importer still validates edits against the current HKX record layout before writing."
        ),
        "entries": entries,
    }


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    'Optional',
    '_hkx_edit_gate_mark_task',
    '_hkx_edit_gate_row',
    '_hkx_edit_gate_task_row',
)
def _hkx_edit_gate_v1_document(
    byte_patch_map: Optional[Mapping[str, object]],
    edit_candidate_map_v1: object,
    native_gate: object,
) -> Dict[str, object]:
    native_gate_map = dict(native_gate) if isinstance(native_gate, Mapping) else {}
    entries = (
        [entry for entry in byte_patch_map.get("entries", []) if isinstance(entry, Mapping)]
        if isinstance(byte_patch_map, Mapping) and isinstance(byte_patch_map.get("entries"), list)
        else []
    )
    native_candidates = (
        [candidate for candidate in edit_candidate_map_v1.get("candidates", []) if isinstance(candidate, Mapping)]
        if isinstance(edit_candidate_map_v1, Mapping) and isinstance(edit_candidate_map_v1.get("candidates"), list)
        else []
    )
    category_rows: Dict[str, Dict[str, object]] = {}
    task_rows: Dict[str, Dict[str, object]] = {}
    for entry in entries:
        category = str(entry.get("category") or "unknown")
        row = _hkx_edit_gate_row(category_rows, category, str(entry.get("owner_class") or ""))
        row["write_enabled_count"] = int(row.get("write_enabled_count") or 0) + 1
        row["status"] = "enabled"
        row["fixed_edit_test_status"] = str(entry.get("fixed_edit_test_status") or "existing_route")
        row["gate_reason"] = str(entry.get("gate_reason") or "exact record offset and value size recovered")
        _hkx_edit_gate_mark_task(category_rows, task_rows, entry, write_enabled=True, reason=str(row["gate_reason"]))
    for candidate in native_candidates:
        category = str(candidate.get("category") or candidate.get("class") or "native_candidate")
        row = _hkx_edit_gate_row(category_rows, category, str(candidate.get("owner_class") or candidate.get("class") or ""))
        if bool(candidate.get("write_enabled")):
            row["write_enabled_count"] = int(row.get("write_enabled_count") or 0) + 1
            row["status"] = "enabled"
            row["fixed_edit_test_status"] = str(candidate.get("fixed_edit_test_status") or "existing_route")
            _hkx_edit_gate_mark_task(category_rows, task_rows, candidate, write_enabled=True, reason=str(candidate.get("gate_reason") or "existing fixed-size patch route"))
        else:
            row["candidate_only_count"] = int(row.get("candidate_only_count") or 0) + 1
            if row.get("status") != "enabled":
                row["status"] = "candidate_only"
                row["fixed_edit_test_status"] = "required"
            _hkx_edit_gate_mark_task(category_rows, task_rows, candidate, write_enabled=False, candidate_only=True)
        row["gate_reason"] = str(candidate.get("gate_reason") or row.get("gate_reason") or "")
    native_categories = native_gate_map.get("categories")
    if isinstance(native_categories, list):
        for native_row in native_categories:
            if not isinstance(native_row, Mapping):
                continue
            row = _hkx_edit_gate_row(category_rows, str(native_row.get("category") or "unknown"), str(native_row.get("owner_class") or ""))
            if row.get("status") != "enabled":
                row["status"] = str(native_row.get("status") or row.get("status") or "blocked")
            row["candidate_only_count"] = max(
                int(row.get("candidate_only_count") or 0),
                int(native_row.get("candidate_only_count") or 0),
            )
            row["gate_reason"] = str(native_row.get("gate_reason") or row.get("gate_reason") or "")
    native_task_categories = native_gate_map.get("task_categories")
    if isinstance(native_task_categories, list):
        for native_row in native_task_categories:
            if not isinstance(native_row, Mapping):
                continue
            row = _hkx_edit_gate_task_row(task_rows, native_row.get("key"))
            if row.get("status") != "enabled":
                row["status"] = str(native_row.get("status") or row.get("status") or "blocked")
            row["write_enabled_count"] = max(
                int(row.get("write_enabled_count") or 0),
                int(native_row.get("write_enabled_count") or 0),
            )
            row["candidate_only_count"] = max(
                int(row.get("candidate_only_count") or 0),
                int(native_row.get("candidate_only_count") or 0),
            )
            row["fixed_edit_test_status"] = str(native_row.get("fixed_edit_test_status") or row.get("fixed_edit_test_status") or "")
            row["gate_reason"] = str(native_row.get("gate_reason") or row.get("gate_reason") or "")
    structural_row = _hkx_edit_gate_row(category_rows, "structural_edits", "*")
    structural_row.update(
        {
            "status": "blocked",
            "write_enabled_count": 0,
            "fixed_edit_test_status": "blocked",
            "gate_reason": "topology/count/reference/string/array edits require semantic rebuild proof",
        }
    )
    required_roles = native_gate_map.get("required_role_coverage")
    if not isinstance(required_roles, list) or not required_roles:
        required_roles = [
            {
                "role": role,
                "no_edit_status": "required",
                "fixed_edit_status": "required",
                "status": "representative_corpus_required",
            }
            for role in ("object", "meshphysics", "character_physics", "ragdoll_body", "mesh_heavy", "animation")
        ]
    blocked_kinds = native_gate_map.get("blocked_kinds")
    if not isinstance(blocked_kinds, list):
        blocked_kinds = ["array", "string", "reference", "topology", "count", "compressed_table", "class_metadata", "shape_primitive_count"]
    write_enabled_count = sum(int(row.get("write_enabled_count") or 0) for row in category_rows.values())
    candidate_only_count = sum(int(row.get("candidate_only_count") or 0) for row in category_rows.values())
    for task_key in ("collision_size", "material_friction", "damping_motion", "joint_strength", "body_transform"):
        _hkx_edit_gate_task_row(task_rows, task_key)
    return {
        "format": "cdmw_hkx_edit_gate_v1",
        "native_format": str(native_gate_map.get("format") or ""),
        "status": str(native_gate_map.get("status") or "fixed_size_patch_gate"),
        "imported": False,
        "read_only": True,
        "new_editable_fields_enabled": False,
        "write_enabled_candidate_count": write_enabled_count,
        "candidate_only_count": candidate_only_count,
        "blocked_policy": str(
            native_gate_map.get("blocked_policy")
            or "Arrays, strings, references, topology, counts, compressed tables, and class metadata remain blocked until semantic rebuild proof."
        ),
        "required_role_coverage": [dict(row) for row in required_roles if isinstance(row, Mapping)],
        "categories": sorted(category_rows.values(), key=lambda row: (str(row.get("status") or ""), str(row.get("category") or ""))),
        "task_categories": sorted(
            task_rows.values(),
            key=lambda row: (
                ["collision_size", "material_friction", "damping_motion", "joint_strength", "body_transform", "mesh_winding", "inspect_only"].index(str(row.get("key")))
                if str(row.get("key")) in {"collision_size", "material_friction", "damping_motion", "joint_strength", "body_transform", "mesh_winding", "inspect_only"}
                else 99
            ),
        ),
        "blocked_kinds": [str(kind) for kind in blocked_kinds],
    }


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Optional',
    '_HKX_MODDING_WORKSPACE_TASKS',
    '_hkx_workspace_row_common',
)
def _hkx_modding_workspace_document(
    byte_patch_map: Optional[Mapping[str, object]],
    edit_candidate_map_v1: object,
    hkx_edit_gate_v1: Mapping[str, object],
    modding_readiness: Mapping[str, object],
) -> Dict[str, object]:
    patch_entries = (
        [entry for entry in byte_patch_map.get("entries", []) if isinstance(entry, Mapping)]
        if isinstance(byte_patch_map, Mapping) and isinstance(byte_patch_map.get("entries"), list)
        else []
    )
    native_candidates = (
        [candidate for candidate in edit_candidate_map_v1.get("candidates", []) if isinstance(candidate, Mapping)]
        if isinstance(edit_candidate_map_v1, Mapping) and isinstance(edit_candidate_map_v1.get("candidates"), list)
        else []
    )
    gate_categories = (
        [row for row in hkx_edit_gate_v1.get("categories", []) if isinstance(row, Mapping)]
        if isinstance(hkx_edit_gate_v1, Mapping) and isinstance(hkx_edit_gate_v1.get("categories"), list)
        else []
    )
    gate_by_category = {str(row.get("category") or ""): row for row in gate_categories}
    task_summaries: Dict[str, Dict[str, object]] = {
        str(task["key"]): {
            "key": str(task["key"]),
            "label": str(task["label"]),
            "patchable_count": 0,
            "candidate_only_count": 0,
            "blocked_count": 0,
        }
        for task in _HKX_MODDING_WORKSPACE_TASKS
    }
    rows: List[Dict[str, object]] = []
    for entry in patch_entries:
        rows.append(_hkx_workspace_row_common(task_summaries, gate_by_category, entry, write_enabled=True, source_kind="byte_patch_map"))
    for candidate in native_candidates:
        rows.append(_hkx_workspace_row_common(task_summaries, gate_by_category, candidate, write_enabled=bool(candidate.get("write_enabled")), source_kind="edit_candidate_map_v1"))
    rows.sort(key=lambda row: (str(row.get("task") or ""), int(row.get("sort_index") or 0), str(row.get("label") or "")))
    readiness_label = str(modding_readiness.get("per_file_label") or "")
    if not readiness_label:
        if any(row.get("write_enabled") for row in rows):
            readiness_label = "Patchable tuning"
        elif rows:
            readiness_label = "Candidate values found"
        else:
            readiness_label = "Read-only decoded"
    return {
        "format": "cdmw_hkx_modding_workspace_v1",
        "read_only": True,
        "imported": False,
        "default_view": True,
        "description": (
            "Guided, evidence-backed HKX physics tuning workspace. It surfaces task-filtered patchable rows first, "
            "candidate-only rows second, and leaves unsafe structural edits blocked."
        ),
        "readiness_label": readiness_label,
        "task_filters": [
            {
                "key": str(task["key"]),
                "label": str(task["label"]),
                "patchable_count": int(task_summaries.get(str(task["key"]), {}).get("patchable_count") or 0),
                "candidate_only_count": int(task_summaries.get(str(task["key"]), {}).get("candidate_only_count") or 0),
                "blocked_count": int(task_summaries.get(str(task["key"]), {}).get("blocked_count") or 0),
            }
            for task in _HKX_MODDING_WORKSPACE_TASKS
        ],
        "row_count": len(rows),
        "patchable_row_count": sum(1 for row in rows if row.get("import_safety") == "Import-safe"),
        "candidate_only_row_count": sum(1 for row in rows if row.get("import_safety") == "Read-only candidate"),
        "blocked_row_count": sum(1 for row in rows if row.get("import_safety") == "Structural blocked"),
        "rows": rows[:4096],
        "truncated_row_count": max(0, len(rows) - 4096),
        "blocked_policy": str(hkx_edit_gate_v1.get("blocked_policy") or ""),
    }
