from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_add_patch_map_entry',
    '_hkx_editable_catalog_semantics',
    '_hkx_editable_shape_field_description',
    '_hkx_editable_shape_subject',
    '_hkx_record_absolute_offset',
)
def _hkx_add_shape_patch_entries(data, entries, shapes, records_by_index, component_offsets3, component_offsets4, plane_offsets):
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        shape_index = shape.get("index")
        shape_label = f"shapes[{shape_index}]" if shape_index is not None else "shapes[]"
        subject = _hkx_editable_shape_subject(shape)
        records_map = shape.get("records")
        if not isinstance(records_map, Mapping):
            continue
        for field_name, element_name, components, stride, value_type, confidence in (
            ("vertices", "v", component_offsets3, 12, "float32", "strong inference"),
            ("planes", "plane", plane_offsets, 16, "float32", "strong inference"),
            ("capsule_endpoints", "point", component_offsets3, 12, "float32", "strong inference"),
        ):
            rows = shape.get(field_name)
            record_index = records_map.get(field_name)
            absolute = _hkx_record_absolute_offset(records_by_index, record_index)
            if not isinstance(rows, list):
                continue
            semantics = _hkx_editable_catalog_semantics(
                {"category": "collision_shape", "name": field_name, "description": _hkx_editable_shape_field_description(shape, field_name)}
            )
            for row_index, row in enumerate(rows):
                if not isinstance(row, list):
                    continue
                for component_index, (component, component_offset) in enumerate(components.items()):
                    if component_index >= len(row):
                        continue
                    _hkx_add_patch_map_entry(
                        entries,
                        data=data,
                        path=f"{shape_label}.{field_name}[{row_index}].{component}",
                        category="collision_shape",
                        name=field_name,
                        subject=subject,
                        owner_class=str(shape.get("shape_type") or "collision_shape"),
                        member=field_name,
                        linked_target=shape_label,
                        record_index=record_index,
                        absolute_data_offset=absolute,
                        relative_offset=row_index * stride + component_offset,
                        byte_size=4,
                        value_type=value_type,
                        row_index=row_index,
                        component=component,
                        confidence=confidence,
                        effect=semantics["effect"],
                        value_constraints=semantics["value_constraints"],
                        description=f"Byte patch target for {element_name} {row_index} component {component}.",
                    )
        for field_name, record_key, fixed_offset in (
            ("sphere_radius", "sphere_radius_shape", 0x68),
            ("capsule_radius", "capsule_radius_shape", 0x68),
        ):
            if field_name not in shape:
                continue
            record_index = records_map.get(record_key)
            absolute = _hkx_record_absolute_offset(records_by_index, record_index)
            semantics = _hkx_editable_catalog_semantics({"category": "collision_shape", "name": field_name})
            _hkx_add_patch_map_entry(
                entries,
                data=data,
                path=f"{shape_label}.{field_name}",
                category="collision_shape",
                name=field_name,
                subject=subject,
                owner_class=str(shape.get("shape_type") or record_key),
                member=field_name,
                linked_target=shape_label,
                record_index=record_index,
                absolute_data_offset=absolute,
                relative_offset=fixed_offset,
                byte_size=4,
                value_type="float32",
                confidence="strong inference",
                effect=semantics["effect"],
                value_constraints=semantics["value_constraints"],
                description=f"Byte patch target for {field_name}.",
            )
        mass_properties = shape.get("mass_properties")
        if isinstance(mass_properties, Mapping):
            rows = mass_properties.get("float_rows")
            record_index = records_map.get("mass_properties")
            absolute = _hkx_record_absolute_offset(records_by_index, record_index)
            semantics = _hkx_editable_catalog_semantics({"category": "collision_shape", "name": "mass_properties"})
            if isinstance(rows, list):
                for row_index, row in enumerate(rows):
                    if not isinstance(row, list):
                        continue
                    for component_index, component in enumerate(("x", "y", "z", "w")):
                        if component_index >= len(row):
                            continue
                        _hkx_add_patch_map_entry(
                            entries,
                            data=data,
                            path=f"{shape_label}.mass_properties.float_rows[{row_index}].{component}",
                            category="collision_shape",
                            name="mass_properties",
                            subject=subject,
                            owner_class="hknpShapeMassProperties",
                            member="mass_properties",
                            linked_target=shape_label,
                            record_index=record_index,
                            absolute_data_offset=absolute,
                            relative_offset=row_index * 16 + component_offsets4[component],
                            byte_size=4,
                            value_type="float32",
                            row_index=row_index,
                            component=component,
                            confidence="experimental",
                            effect=semantics["effect"],
                            value_constraints=semantics["value_constraints"],
                            description="Byte patch target for hknpShapeMassProperties float row.",
                        )
        shape_payload = shape.get("shape_payload")
        if isinstance(shape_payload, Mapping):
            slots = shape_payload.get("float_slots")
            record_index = records_map.get("shape_payload")
            absolute = _hkx_record_absolute_offset(records_by_index, record_index)
            semantics = _hkx_editable_catalog_semantics({"category": "collision_shape", "name": "shape_payload"})
            if isinstance(slots, list):
                for slot_index, slot in enumerate(slots):
                    if not isinstance(slot, Mapping) or not isinstance(slot.get("offset"), int):
                        continue
                    offset = int(slot["offset"])
                    _hkx_add_patch_map_entry(
                        entries,
                        data=data,
                        path=f"{shape_label}.shape_payload.float_slots[{slot_index}]",
                        category="collision_shape",
                        name=str(slot.get("name") or "shape_payload"),
                        subject=subject,
                        owner_class=str(shape.get("shape_type") or "hknpShape"),
                        member=str(slot.get("name") or "shape_payload"),
                        linked_target=shape_label,
                        record_index=record_index,
                        absolute_data_offset=absolute,
                        relative_offset=offset,
                        byte_size=4,
                        value_type="float32",
                        row_index=slot_index,
                        component="value",
                        confidence=str(slot.get("confidence") or "experimental"),
                        effect=semantics["effect"],
                        value_constraints=semantics["value_constraints"],
                        description=str(slot.get("description") or "Byte patch target for hknp shape payload float."),
                    )


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_add_patch_map_entry',
    '_hkx_editable_catalog_semantics',
)
def _hkx_add_tuning_patch_entries(data, entries, physics_tuning, records_by_index):
    if isinstance(physics_tuning, Mapping):
        groups = physics_tuning.get("groups")
        if isinstance(groups, list):
            for group_index, group in enumerate(groups):
                if not isinstance(group, Mapping):
                    continue
                record_index = group.get("record_index")
                record = records_by_index.get(record_index) if isinstance(record_index, int) else None
                if record is None or record.absolute_data_offset is None or not record.count:
                    continue
                byte_length = group.get("byte_length")
                try:
                    stride = int(byte_length) // int(record.count)
                except (TypeError, ValueError, ZeroDivisionError):
                    stride = 0
                if stride <= 0:
                    continue
                slots = group.get("slots")
                if not isinstance(slots, list):
                    continue
                for slot_index, slot in enumerate(slots):
                    if not isinstance(slot, Mapping):
                        continue
                    item_index = slot.get("item_index")
                    offset = slot.get("offset")
                    if not isinstance(item_index, int) or not isinstance(offset, int):
                        continue
                    semantics = _hkx_editable_catalog_semantics(
                        {
                            "category": str(group.get("category") or "physics_tuning"),
                            "name": str(slot.get("name") or ""),
                            "description": str(slot.get("description") or ""),
                        }
                    )
                    _hkx_add_patch_map_entry(
                        entries,
                        data=data,
                        path=f"physics_tuning.groups[{group_index}].slots[{slot_index}]",
                        category=str(group.get("category") or "physics_tuning"),
                        name=str(slot.get("name") or ""),
                        subject=str(group.get("label") or group.get("type_name") or ""),
                        owner_class=str(group.get("type_name") or "physics_tuning"),
                        member=str(slot.get("name") or ""),
                        linked_target=str(group.get("label") or group.get("type_name") or ""),
                        linked_by="typed_layout",
                        record_index=record.index,
                        absolute_data_offset=int(record.absolute_data_offset),
                        relative_offset=item_index * stride + offset,
                        local_offset=offset,
                        byte_size=4,
                        value_type="float32",
                        item_index=item_index,
                        component="value",
                        confidence=str(slot.get("confidence") or "experimental"),
                        effect=semantics["effect"],
                        value_constraints=semantics["value_constraints"],
                        description=str(slot.get("description") or "Byte patch target for fixed-offset physics tuning float."),
                    )


@bind_archive_hkx_globals(
    'Dict',
)
def _hkx_edit_gate_row(category_rows: Dict[str, Dict[str, object]], category: str, owner_class: str = "") -> Dict[str, object]:
    key = category or "unknown"
    row = category_rows.get(key)
    if row is None:
        row = {
            "category": key,
            "owner_class": owner_class,
            "status": "blocked",
            "write_enabled_count": 0,
            "candidate_only_count": 0,
            "fixed_edit_test_status": "required",
            "gate_reason": "no approved fixed-size patch target",
        }
        category_rows[key] = row
    if owner_class and not row.get("owner_class"):
        row["owner_class"] = owner_class
    return row


@bind_archive_hkx_globals(
    'Dict',
    '_hkx_patch_map_task_label',
)
def _hkx_edit_gate_task_row(task_rows: Dict[str, Dict[str, object]], task_key: object) -> Dict[str, object]:
    key = str(task_key or "inspect_only")
    row = task_rows.get(key)
    if row is None:
        row = {
            "key": key,
            "label": _hkx_patch_map_task_label(key),
            "status": "blocked",
            "write_enabled_count": 0,
            "candidate_only_count": 0,
            "fixed_edit_test_status": "required",
            "gate_reason": "no approved fixed-size patch target",
        }
        task_rows[key] = row
    return row


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_patch_map_task_key',
)
def _hkx_edit_gate_task_key_for_source(source: Mapping[str, object]) -> str:
    explicit = source.get("task_category")
    if explicit:
        return str(explicit)
    return _hkx_patch_map_task_key(
        str(source.get("category") or ""),
        str(source.get("name") or source.get("member") or source.get("field") or ""),
        str(source.get("owner_class") or source.get("class") or ""),
        str(source.get("member") or source.get("field") or ""),
        str(source.get("description") or source.get("effect") or ""),
    )


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    '_hkx_edit_gate_task_row',
    '_hkx_edit_gate_task_key_for_source',
)
def _hkx_edit_gate_mark_task(category_rows: Dict[str, Dict[str, object]], task_rows: Dict[str, Dict[str, object]], source: Mapping[str, object], *, write_enabled: bool, candidate_only: bool = False, reason: str = "") -> None:
    task_row = _hkx_edit_gate_task_row(task_rows, _hkx_edit_gate_task_key_for_source(source))
    if write_enabled:
        task_row["write_enabled_count"] = int(task_row.get("write_enabled_count") or 0) + 1
        task_row["status"] = "enabled"
        task_row["fixed_edit_test_status"] = str(source.get("fixed_edit_test_status") or "existing_route")
        task_row["gate_reason"] = reason or str(source.get("gate_reason") or "existing fixed-size patch route")
    elif candidate_only:
        task_row["candidate_only_count"] = int(task_row.get("candidate_only_count") or 0) + 1
        if task_row.get("status") != "enabled":
            task_row["status"] = "candidate_only"
            task_row["fixed_edit_test_status"] = "required"
            task_row["gate_reason"] = reason or str(source.get("gate_reason") or "decoded candidate lacks fixed-edit proof")


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_workspace_offset_text(row: Mapping[str, object]) -> str:
    for key in ("absolute_offset_hex", "hex_absolute_data_offset", "offset_hex", "hex_relative_offset"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    for key in ("absolute_offset", "absolute_data_offset", "record_relative_offset", "relative_offset", "local_offset", "offset"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return f"0x{int(value):X}"
        except (TypeError, ValueError):
            text = str(value).strip()
            if text:
                return text
    return ""


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    '_hkx_workspace_label_for_link',
    '_hkx_workspace_label_for_safety',
    '_hkx_workspace_label_for_value_kind',
    '_hkx_workspace_offset_text',
    '_hkx_workspace_task_key_for_text',
    '_hkx_workspace_task_label',
)
def _hkx_workspace_row_common(task_summaries: Dict[str, Dict[str, object]], gate_by_category: Mapping[str, Mapping[str, object]], source: Mapping[str, object], *, write_enabled: bool, source_kind: str) -> Dict[str, object]:
    category = str(source.get("category") or source.get("class") or source.get("owner_class") or "unknown")
    gate_row = gate_by_category.get(category, {})
    structural_kind = source.get("structural_kind") or source.get("value_kind") or ""
    value_kind = source.get("value_kind") or source.get("write_type") or source.get("supported_write_type") or ""
    linked_by = source.get("linked_by") or source.get("link_evidence") or source.get("evidence") or ""
    task_key = str(source.get("task_category") or "").strip() or _hkx_workspace_task_key_for_text(
        category,
        source.get("owner_class"),
        source.get("member"),
        source.get("field"),
        source.get("name"),
        source.get("description"),
        source.get("effect"),
        source.get("linked_target"),
    )
    safety_label = _hkx_workspace_label_for_safety(
        source.get("import_safety") or source.get("gate_status"),
        write_enabled=write_enabled,
        structural_kind=structural_kind,
    )
    if str(source.get("gate_status") or "").strip().casefold() == "candidate_only":
        safety_label = "Read-only candidate"
    if str(source.get("gate_status") or "").strip().casefold() == "blocked":
        safety_label = "Structural blocked"
    summary = task_summaries.setdefault(
        task_key,
        {"key": task_key, "label": _hkx_workspace_task_label(task_key), "patchable_count": 0, "candidate_only_count": 0, "blocked_count": 0},
    )
    if safety_label == "Import-safe":
        summary["patchable_count"] = int(summary.get("patchable_count") or 0) + 1
        sort_group = "patchable"
        sort_index = 0
    elif safety_label == "Read-only candidate":
        summary["candidate_only_count"] = int(summary.get("candidate_only_count") or 0) + 1
        sort_group = "candidate_only"
        sort_index = 1
    else:
        summary["blocked_count"] = int(summary.get("blocked_count") or 0) + 1
        sort_group = "blocked"
        sort_index = 2
    owner_class = str(source.get("owner_class") or source.get("class") or "")
    member = str(source.get("member") or source.get("field") or source.get("name") or "")
    linked_target = str(source.get("linked_target") or source.get("subject") or "")
    label = str(source.get("path") or "").strip()
    if not label:
        label = " ".join(part for part in (owner_class, member) if part).strip() or category
    meaning = str(source.get("effect") or source.get("description") or source.get("gate_reason") or "")
    original = source.get("decoded_value")
    if original is None:
        original = source.get("original_value")
    if original is None:
        original = source.get("value")
    current = original
    record = source.get("record_index")
    if record is None:
        record = source.get("record")
    return {
        "task": task_key,
        "task_label": _hkx_workspace_task_label(task_key),
        "sort_group": sort_group,
        "sort_index": sort_index,
        "source": source_kind,
        "category": category,
        "category_label": str(source.get("category_label") or source.get("task_label") or ""),
        "label": label,
        "owner_class": owner_class,
        "member": member,
        "meaning": meaning,
        "import_safety": safety_label,
        "structural_kind": _hkx_workspace_label_for_value_kind(value_kind or structural_kind),
        "risk": str(source.get("risk_label") or source.get("risk") or gate_row.get("fixed_edit_test_status") or "unknown"),
        "evidence": str(source.get("confidence") or source.get("evidence") or gate_row.get("fixed_edit_test_status") or ""),
        "linked_by": _hkx_workspace_label_for_link(linked_by),
        "record": "" if record is None else str(record),
        "item": "" if source.get("item_index") is None else str(source.get("item_index")),
        "offset": _hkx_workspace_offset_text(source),
        "byte_size": "" if source.get("byte_size") is None else str(source.get("byte_size")),
        "original": "" if original is None else str(original),
        "current": "" if current is None else str(current),
        "linked_target": linked_target,
        "relationship_chain": " -> ".join(
            part
            for part in (
                f"body/record {record}" if str(category).casefold().find("body") >= 0 and record is not None else "",
                linked_target,
                owner_class,
                member,
            )
            if str(part or "").strip()
        ),
        "gate_status": str(source.get("gate_status") or gate_row.get("status") or ""),
        "gate_reason": str(source.get("gate_reason") or gate_row.get("gate_reason") or ""),
        "write_enabled": bool(write_enabled),
        "import_behavior": str(source.get("import_behavior") or ""),
    }
