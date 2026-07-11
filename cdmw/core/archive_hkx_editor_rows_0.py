from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Optional',
    'Sequence',
    'Tuple',
    're',
)
def _hkx_editor_build_context(
    shapes: Sequence[Mapping[str, object]],
    byte_patch_map: Optional[Mapping[str, object]],
    objects: Sequence[Mapping[str, object]],
    physics_body_summary: Optional[Mapping[str, object]],
) -> Tuple[List[str], Dict[str, List[Dict[str, object]]], Dict[Tuple[str, str], Mapping[str, object]], Dict[int, int], Dict[str, Dict[str, object]]]:
    group_order = [
        "bodies",
        "collision_shapes",
        "constraints",
        "motors",
        "motion_damping",
        "object_records",
        "raw_preserved_data",
    ]
    rows_by_group: Dict[str, List[Dict[str, object]]] = {group: [] for group in group_order}
    patch_entries_by_shape_field: Dict[Tuple[str, str], Mapping[str, object]] = {}
    if isinstance(byte_patch_map, Mapping):
        for entry in byte_patch_map.get("entries", []) if isinstance(byte_patch_map.get("entries"), list) else []:
            if isinstance(entry, Mapping):
                entry_path = str(entry.get("path") or "")
                shape_field_match = re.match(r"^shapes\[(\d+)\]\.([A-Za-z_][A-Za-z0-9_]*)", entry_path)
                if shape_field_match:
                    patch_entries_by_shape_field.setdefault((shape_field_match.group(1), shape_field_match.group(2)), entry)
    shape_index_by_record_index = {
        int(shape.get("shape_record_index")): int(shape.get("index"))
        for shape in shapes
        if isinstance(shape, Mapping)
        and isinstance(shape.get("shape_record_index"), int)
        and isinstance(shape.get("index"), int)
    }
    body_record_shape_links: Dict[int, int] = {}
    for object_info in objects:
        if not isinstance(object_info, Mapping):
            continue
        if str(object_info.get("type_name") or "") != "hknpPhysicsSystemData::ExtendedBodyCinfo":
            continue
        record_index = object_info.get("record_index")
        references = object_info.get("references")
        if not isinstance(record_index, int) or not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            target_record_index = reference.get("target_record_index")
            if isinstance(target_record_index, int) and target_record_index in shape_index_by_record_index:
                body_record_shape_links[int(record_index)] = shape_index_by_record_index[target_record_index]
                break
    body_context_by_shape_index: Dict[str, Dict[str, object]] = {}
    if isinstance(physics_body_summary, Mapping):
        for body in physics_body_summary.get("bodies", []) if isinstance(physics_body_summary.get("bodies"), list) else []:
            if not isinstance(body, Mapping):
                continue
            shape_index = body.get("shape_index")
            if shape_index in (None, ""):
                continue
            primary_context: Mapping[str, object] = {}
            descriptor_contexts = body.get("descriptor_contexts")
            if isinstance(descriptor_contexts, list):
                primary_context = next((context for context in descriptor_contexts if isinstance(context, Mapping)), {})
            body_context_by_shape_index[str(shape_index)] = {
                "body_name": body.get("body_name") or primary_context.get("body_name"),
                "socket_name": body.get("socket_name") or primary_context.get("socket_name"),
                "fixed_socket_name": body.get("fixed_socket_name") or primary_context.get("fixed_socket_name"),
                "physics_material_name": body.get("physics_material_name") or primary_context.get("physics_material_name"),
                "shape_index": shape_index,
                "shape_type": body.get("shape_type"),
                "context_source": primary_context.get("descriptor_path") or "physics_body_summary",
                "context_confidence": body.get("confidence") or primary_context.get("confidence") or "experimental",
            }
    return group_order, rows_by_group, patch_entries_by_shape_field, body_record_shape_links, body_context_by_shape_index


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_editor_context_label(context: Mapping[str, object], fallback: object = "") -> str:
    for key in ("body_name", "socket_name", "fixed_socket_name", "physics_material_name"):
        value = str(context.get(key) or "").strip()
        if value:
            return value
    return str(fallback or "").strip()


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_editor_context_identity_path(context: Mapping[str, object], field_name: object = "") -> str:
    parts = []
    for label, key in (
        ("body", "body_name"),
        ("socket", "socket_name"),
        ("fixed_socket", "fixed_socket_name"),
        ("material", "physics_material_name"),
    ):
        value = str(context.get(key) or "").strip()
        if value:
            parts.append(f"{label}:{value}")
    shape_index = context.get("shape_index")
    if shape_index not in (None, ""):
        parts.append(f"shape/{shape_index}")
    if field_name not in (None, "") and str(field_name).strip():
        parts.append(str(field_name).strip())
    return " -> ".join(parts)


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    '_hkx_editor_context_identity_path',
    '_hkx_editor_context_label',
)
def _hkx_editor_context_kwargs_for_shape(body_context_by_shape_index: Mapping[str, Mapping[str, object]], shape_index: object, field_name: object = "", fallback_label: object = "") -> Dict[str, object]:
    if shape_index in (None, ""):
        return {}
    context = body_context_by_shape_index.get(str(shape_index))
    if not isinstance(context, Mapping):
        fallback = str(fallback_label or "").strip()
        return {
            "shape_index": shape_index,
            "context_label": fallback,
            "display_label": f"{fallback}: {field_name}" if fallback and field_name else fallback or str(field_name or ""),
            "identity_path": f"shape/{shape_index} -> {field_name}".strip(" ->") if field_name else f"shape/{shape_index}",
        }
    label = _hkx_editor_context_label(context, fallback_label)
    result = dict(context)
    result["context_label"] = label
    result["display_label"] = f"{label}: {field_name}" if label and field_name else label or str(fallback_label or "")
    result["identity_path"] = _hkx_editor_context_identity_path(context, field_name)
    return result


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Optional',
    '_hkx_editor_add_row',
    '_hkx_editor_context_kwargs_for_shape',
    '_hkx_editor_selection_id',
    '_hkx_xml_scalar',
)
def _hkx_editor_add_body_rows(rows_by_group: Dict[str, List[Dict[str, object]]], physics_body_summary: Optional[Mapping[str, object]], body_context_by_shape_index: Mapping[str, Mapping[str, object]]) -> None:
    if isinstance(physics_body_summary, Mapping):
        for body in physics_body_summary.get("bodies", []) if isinstance(physics_body_summary.get("bodies"), list) else []:
            if not isinstance(body, Mapping):
                continue
            body_name = str(body.get("body_name") or f"shape {body.get('shape_index') or ''}").strip()
            shape_type = str(body.get("shape_type") or "")
            capsule = body.get("capsule")
            value = ""
            if isinstance(capsule, Mapping):
                radius = capsule.get("radius")
                length = capsule.get("length")
                value = "; ".join(
                    part
                    for part in (
                        f"radius={_hkx_xml_scalar(radius)}" if radius is not None else "",
                        f"length={_hkx_xml_scalar(length)}" if length is not None else "",
                    )
                    if part
                )
            _hkx_editor_add_row(
                rows_by_group,
                "bodies",
                label=body_name or "body",
                subject=shape_type,
                value=value,
                value_type="summary",
                confidence=str(body.get("confidence") or "experimental"),
                effect=str(body.get("simulation_role") or "body context"),
                explanation=str(body.get("description") or "Decoded body/shape context for identifying editable physics values."),
                source="physics_body_summary",
                viewer_selection_id=_hkx_editor_selection_id("shape", body.get("shape_index")),
                **_hkx_editor_context_kwargs_for_shape(body_context_by_shape_index, body.get("shape_index"), "body summary", body_name or "body"),
            )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    '_hkx_compact_vector',
    '_hkx_editable_shape_subject',
    '_hkx_editor_add_row',
    '_hkx_editor_context_kwargs_for_shape',
    '_hkx_editor_selection_id',
)
def _hkx_editor_add_shape_summary(rows_by_group: Dict[str, List[Dict[str, object]]], shape: Mapping[str, object], body_context_by_shape_index: Mapping[str, Mapping[str, object]]) -> None:
    shape_index = shape.get("index")
    shape_type = str(shape.get("shape_type") or "hknpShape")
    subject = _hkx_editable_shape_subject(shape)
    summary_parts = [shape_type]
    for key, label in (("center", "center"), ("extent", "extent")):
        value = shape.get(key)
        if isinstance(value, list) and len(value) == 3:
            summary_parts.append(f"{label}={_hkx_compact_vector(value)}")
    shape_record_index = shape.get("shape_record_index")
    if shape_record_index is not None:
        summary_parts.append(f"record={shape_record_index}")
    read_only_reason = str(shape.get("read_only_reason") or "")
    _hkx_editor_add_row(
        rows_by_group,
        "collision_shapes",
        label=f"{subject}: summary" if subject else f"shape {shape_index}: summary",
        subject=subject or shape_type,
        field="summary",
        value="; ".join(summary_parts),
        value_type="decoded shape summary",
        importable=False,
        editor_tab="Overview",
        record_index=shape_record_index,
        confidence="strong inference"
        if shape_type in {"hknpConvexShape", "hknpBoxShape", "hknpSphereShape", "hknpCapsuleShape"}
        else "experimental",
        edit_risk="not editable",
        effect="collision volume / preview target",
        explanation=(
            read_only_reason
            or "Decoded collision shape summary. This row is for browsing, filtering, and 3D preview selection; edit supported child values where available."
        ),
        safe_edit_hint="Read-only summary row. Use editable child rows or XML fixed-size fields where available.",
        source="collision_shapes",
        viewer_selection_id=_hkx_editor_selection_id("shape", shape_index),
        **_hkx_editor_context_kwargs_for_shape(body_context_by_shape_index, shape_index, "summary", subject or shape_type),
    )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Tuple',
    '_hkx_editable_catalog_semantics',
    '_hkx_editable_shape_field_description',
    '_hkx_editable_shape_field_value_summary',
    '_hkx_editable_shape_subject',
    '_hkx_editor_add_row',
    '_hkx_editor_context_kwargs_for_shape',
    '_hkx_editor_selection_id',
)
def _hkx_editor_add_shape_field_rows(rows_by_group: Dict[str, List[Dict[str, object]]], shape: Mapping[str, object], patch_entries_by_shape_field: Mapping[Tuple[str, str], Mapping[str, object]], body_context_by_shape_index: Mapping[str, Mapping[str, object]]) -> None:
    shape_index = shape.get("index")
    shape_type = str(shape.get("shape_type") or "hknpShape")
    subject = _hkx_editable_shape_subject(shape)
    for field_name in shape.get("editable_fields", []) if isinstance(shape.get("editable_fields"), list) else []:
        field_name = str(field_name or "")
        if not field_name:
            continue
        value_summary = _hkx_editable_shape_field_value_summary(shape, field_name)
        patch_path = ""
        if field_name in {"sphere_radius", "capsule_radius"}:
            patch_path = f"shapes[{shape_index}].{field_name}"
        elif field_name in {"vertices", "planes", "capsule_endpoints"}:
            patch_path = f"shapes[{shape_index}].{field_name}[0]"
        patch_entry = patch_entries_by_shape_field.get((str(shape_index), field_name))
        semantics = _hkx_editable_catalog_semantics(
            {
                "category": "collision_shape",
                "name": field_name,
                "description": _hkx_editable_shape_field_description(shape, field_name),
            }
        )
        _hkx_editor_add_row(
            rows_by_group,
            "collision_shapes",
            label=f"{subject}: {field_name}" if subject else f"shape {shape_index}: {field_name}",
            subject=subject or shape_type,
            field=field_name,
            value=value_summary,
            value_type="number/vector/table",
            importable=True,
            patch_path=patch_path or f"shapes[{shape_index}].{field_name}",
            editor_tab="Collision Editor",
            record_index=(patch_entry or {}).get("record_index") if isinstance(patch_entry, Mapping) else None,
            byte_offset=(patch_entry or {}).get("absolute_data_offset") if isinstance(patch_entry, Mapping) else None,
            confidence="strong inference" if field_name in {"vertices", "planes", "capsule_radius", "capsule_endpoints", "sphere_radius", "sphere_center"} else "experimental",
            edit_risk=str(semantics.get("edit_risk") or ""),
            effect=str(semantics.get("effect") or "collision volume"),
            explanation=_hkx_editable_shape_field_description(shape, field_name),
            safe_edit_hint=str(semantics.get("edit_guidance") or ""),
            value_constraints=str(semantics.get("value_constraints") or ""),
            source="shapes",
            viewer_selection_id=_hkx_editor_selection_id("shape", shape_index),
            **_hkx_editor_context_kwargs_for_shape(body_context_by_shape_index, shape_index, field_name, subject or shape_type),
        )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    '_hkx_editable_shape_subject',
    '_hkx_editor_add_row',
    '_hkx_editor_context_kwargs_for_shape',
    '_hkx_editor_selection_id',
)
def _hkx_editor_add_shape_mesh_rows(rows_by_group: Dict[str, List[Dict[str, object]]], shape: Mapping[str, object], body_context_by_shape_index: Mapping[str, Mapping[str, object]]) -> None:
    shape_index = shape.get("index")
    shape_type = str(shape.get("shape_type") or "hknpShape")
    subject = _hkx_editable_shape_subject(shape)
    shape_record_index = shape.get("shape_record_index")
    mesh_details = shape.get("mesh_details")
    if isinstance(mesh_details, Mapping):
        editability = mesh_details.get("editability")
        if isinstance(editability, Mapping):
            blocked_operations = editability.get("blocked_operations")
            blocked_summary = ", ".join(str(item) for item in blocked_operations[:4]) if isinstance(blocked_operations, list) else ""
            _hkx_editor_add_row(
                rows_by_group,
                "collision_shapes",
                label=f"{subject}: mesh editability",
                subject=subject or shape_type,
                field="mesh_editability",
                value=str(editability.get("status") or "blocked"),
                value_type="read-only safety gate",
                importable=False,
                editor_tab="Collision Editor",
                record_index=shape_record_index,
                confidence="confirmed",
                edit_risk="not editable",
                effect="mesh-shape topology safety",
                explanation=(
                    "Mesh-shape topology editing is disabled until geometry sections, packed primitive words, "
                    "AABB nodes, and shape-tag ranges are decoded well enough to rebuild them safely."
                ),
                safe_edit_hint=str(editability.get("safe_current_behavior") or "") + (f"; blocked: {blocked_summary}" if blocked_summary else ""),
                value_constraints="read-only; no primitive, AABB, shape-tag, or byte-buffer length changes",
                source="mesh_details",
                viewer_selection_id=_hkx_editor_selection_id("shape", shape_index),
                **_hkx_editor_context_kwargs_for_shape(body_context_by_shape_index, shape_index, "mesh editability", subject or shape_type),
            )
            supported_operations = editability.get("supported_safe_operations")
            if isinstance(supported_operations, list) and supported_operations:
                _hkx_editor_add_row(
                    rows_by_group,
                    "collision_shapes",
                    label=f"{subject}: supported mesh edit",
                    subject=subject or shape_type,
                    field="mesh_supported_safe_operation",
                    value="; ".join(str(operation) for operation in supported_operations[:3]),
                    value_type="guarded mesh edit",
                    importable=False,
                    editor_tab="Collision Editor",
                    record_index=shape_record_index,
                    confidence="strong inference",
                    edit_risk="guarded",
                    effect="mesh primitive winding/order",
                    explanation=(
                        "Primitive tuple winding can be edited when each primitive keeps the same vertex-index set. "
                        "This changes only tuple byte order and does not rebuild primitive counts, shape tags, or AABB data."
                    ),
                    safe_edit_hint="Use XML/JSON mesh_details primitive byte_indices for winding flips only.",
                    value_constraints="same primitive count; same four-byte tuple length; same non-0xFF index set per primitive",
                    source="mesh_details",
                    viewer_selection_id=_hkx_editor_selection_id("shape", shape_index),
                    **_hkx_editor_context_kwargs_for_shape(body_context_by_shape_index, shape_index, "supported mesh edit", subject or shape_type),
                )
        primitive_analysis = mesh_details.get("primitive_analysis_summary")
        if isinstance(primitive_analysis, list):
            for analysis in primitive_analysis[:8]:
                if not isinstance(analysis, Mapping):
                    continue
                _hkx_editor_add_row(
                    rows_by_group,
                    "collision_shapes",
                    label=f"{subject}: primitive analysis record {analysis.get('record_index')}",
                    subject=subject or shape_type,
                    field="mesh_primitive_analysis",
                    value=(
                        f"count={analysis.get('count')}; vertex_index_range={analysis.get('candidate_index_range')}; "
                        f"quads={analysis.get('candidate_quad_count')}; triangles={analysis.get('candidate_triangle_count')}"
                    ),
                    value_type="read-only topology candidate",
                    importable=False,
                    editor_tab="Collision Editor",
                    record_index=analysis.get("record_index"),
                    confidence="experimental",
                    edit_risk="not editable",
                    effect="mesh primitive browser",
                    explanation=(
                        "Four-byte primitive tuple summary for schema recovery. It helps identify vertex-index "
                        "ranges and triangle/quad candidates, but is not a safe edit target yet."
                    ),
                    safe_edit_hint="Use this for comparing mesh-shape files; topology, AABB, and shape-tag rebuilds are still blocked.",
                    source="mesh_details",
                    viewer_selection_id=_hkx_editor_selection_id("shape", shape_index),
                    **_hkx_editor_context_kwargs_for_shape(body_context_by_shape_index, shape_index, "primitive analysis", subject or shape_type),
                )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Sequence',
    'Tuple',
    '_hkx_editor_add_shape_field_rows',
    '_hkx_editor_add_shape_mesh_rows',
    '_hkx_editor_add_shape_summary',
)
def _hkx_editor_add_shape_rows(
    rows_by_group: Dict[str, List[Dict[str, object]]],
    shapes: Sequence[Mapping[str, object]],
    patch_entries_by_shape_field: Mapping[Tuple[str, str], Mapping[str, object]],
    body_context_by_shape_index: Mapping[str, Mapping[str, object]],
) -> None:
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        _hkx_editor_add_shape_summary(rows_by_group, shape, body_context_by_shape_index)
        _hkx_editor_add_shape_field_rows(rows_by_group, shape, patch_entries_by_shape_field, body_context_by_shape_index)
        _hkx_editor_add_shape_mesh_rows(rows_by_group, shape, body_context_by_shape_index)


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Optional',
    '_hkx_editor_add_row',
    '_hkx_editor_context_identity_path',
    '_hkx_editor_context_label',
    '_hkx_editor_selection_id',
    '_hkx_physics_tuning_user_guidance',
)
def _hkx_editor_add_constraint_rows(rows_by_group: Dict[str, List[Dict[str, object]]], physics_constraint_summary: Optional[Mapping[str, object]]) -> None:
    if isinstance(physics_constraint_summary, Mapping):
        for constraint in physics_constraint_summary.get("constraints", []) if isinstance(physics_constraint_summary.get("constraints"), list) else []:
            if not isinstance(constraint, Mapping):
                continue
            constraint_name = str(constraint.get("name") or f"constraint {constraint.get('index') or ''}")
            descriptor_context = constraint.get("descriptor_context")
            constraint_context_kwargs: Dict[str, object] = {}
            if isinstance(descriptor_context, Mapping):
                context_label = _hkx_editor_context_label(
                    descriptor_context,
                    constraint_name,
                )
                constraint_context_kwargs = {
                    "context_label": context_label,
                    "display_label": f"{context_label}: {constraint_name}" if context_label else constraint_name,
                    "body_name": descriptor_context.get("body_name"),
                    "socket_name": descriptor_context.get("socket_name"),
                    "fixed_socket_name": descriptor_context.get("fixed_socket_name"),
                    "context_source": descriptor_context.get("descriptor_path") or "constraint_descriptor_context",
                    "context_confidence": descriptor_context.get("confidence") or "descriptor_context",
                    "identity_path": _hkx_editor_context_identity_path(descriptor_context, constraint_name),
                }
            _hkx_editor_add_row(
                rows_by_group,
                "constraints",
                label=constraint_name,
                subject=str(constraint.get("type_name") or ""),
                value=f"constraint_record={constraint.get('constraint_record_index')}; motor_record={constraint.get('motor_record_index')}",
                value_type="summary",
                confidence=str(constraint.get("confidence") or "experimental"),
                effect="joint limits / constraint behavior",
                explanation=str(constraint.get("description") or "Constraint summary; edit linked slots in Structured Editor."),
                source="physics_constraint_summary",
                viewer_selection_id=_hkx_editor_selection_id("constraint", constraint.get("index")),
                **constraint_context_kwargs,
            )
            for slot_group_name, group_name in (("constraint_slots", "constraints"), ("motor_slots", "motors")):
                for slot in constraint.get(slot_group_name, []) if isinstance(constraint.get(slot_group_name), list) else []:
                    if not isinstance(slot, Mapping):
                        continue
                    record_index = constraint.get("motor_record_index") if slot_group_name == "motor_slots" else constraint.get("constraint_record_index")
                    try:
                        item_index = int(slot.get("item_index"))
                        offset = int(slot.get("offset"))
                    except (TypeError, ValueError):
                        item_index = None
                        offset = None
                    guidance = _hkx_physics_tuning_user_guidance(str(slot.get("source_type_name") or constraint.get("type_name") or ""), int(offset or 0), str(slot.get("name") or ""))
                    _hkx_editor_add_row(
                        rows_by_group,
                        group_name,
                        label=f"{constraint_name}: {slot.get('name') or 'slot'}",
                        subject=constraint_name,
                        field=str(slot.get("name") or ""),
                        value=slot.get("value"),
                        value_type="float32",
                        importable=True,
                        patch_path=f"physics_tuning record {record_index} item {item_index} offset 0x{int(offset or 0):X}",
                        editor_tab="Structured Editor",
                        record_index=record_index,
                        item_index=item_index,
                        offset=offset,
                        confidence=str(slot.get("confidence") or "experimental"),
                        edit_risk=str(guidance.get("edit_risk") or ""),
                        effect=str(guidance.get("plain_language_effect") or ""),
                        explanation=str(slot.get("description") or ""),
                        if_increased=str(guidance.get("if_increased") or ""),
                        if_decreased=str(guidance.get("if_decreased") or ""),
                        safe_edit_hint=str(guidance.get("safe_edit_hint") or ""),
                        value_constraints=str(guidance.get("value_constraints") or ""),
                        source="physics_constraint_summary",
                        viewer_selection_id=_hkx_editor_selection_id("constraint", constraint.get("index")),
                        **{
                            **constraint_context_kwargs,
                            "display_label": (
                                f"{constraint_context_kwargs.get('context_label')}: {slot.get('name') or 'slot'}"
                                if constraint_context_kwargs.get("context_label")
                                else f"{constraint_name}: {slot.get('name') or 'slot'}"
                            ),
                            "identity_path": (
                                f"{constraint_context_kwargs.get('identity_path')} -> {slot.get('name') or 'slot'}"
                                if constraint_context_kwargs.get("identity_path")
                                else f"constraint/{constraint.get('index')} -> {slot.get('name') or 'slot'}"
                            ),
                        },
                    )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Optional',
    '_hkx_editor_add_row',
    '_hkx_editor_context_kwargs_for_shape',
    '_hkx_editor_selection_id',
    '_hkx_xml_scalar',
)
def _hkx_editor_add_tuning_rows(rows_by_group: Dict[str, List[Dict[str, object]]], physics_tuning: Optional[Mapping[str, object]], body_record_shape_links: Mapping[int, int], body_context_by_shape_index: Mapping[str, Mapping[str, object]]) -> None:
    if isinstance(physics_tuning, Mapping):
        for group_index, group in enumerate(physics_tuning.get("groups", []) if isinstance(physics_tuning.get("groups"), list) else []):
            if not isinstance(group, Mapping):
                continue
            category = str(group.get("category") or "physics_tuning")
            target_group = "motors" if category == "motor_force_response" else "motion_damping" if category == "motion_damping_solver" else "constraints" if category == "joint_limits_strength" else "bodies"
            linked_shape_index = body_record_shape_links.get(int(group.get("record_index"))) if isinstance(group.get("record_index"), int) else None
            group_viewer_selection_id = (
                _hkx_editor_selection_id("shape", linked_shape_index)
                if linked_shape_index is not None
                else _hkx_editor_selection_id("record", group.get("record_index"))
            )
            group_context_kwargs = _hkx_editor_context_kwargs_for_shape(body_context_by_shape_index,
                linked_shape_index,
                "",
                str(group.get("label") or group.get("type_name") or category),
            )
            group_owner_label = str(
                group_context_kwargs.get("context_label")
                or group.get("label")
                or group.get("type_name")
                or category
            )
            for vector_group in group.get("slot_vector_groups", []) if isinstance(group.get("slot_vector_groups"), list) else []:
                if not isinstance(vector_group, Mapping):
                    continue
                components = vector_group.get("components")
                value = ""
                if isinstance(components, Mapping):
                    value = " ".join(
                        f"{component}={_hkx_xml_scalar(components.get(component))}"
                        for component in ("x", "y", "z", "w")
                        if component in components
                    )
                _hkx_editor_add_row(
                    rows_by_group,
                    target_group,
                    label=f"{group_owner_label}: {vector_group.get('name') or 'vector'}",
                    subject=str(group_owner_label or group.get("type_name") or ""),
                    field=str(vector_group.get("name") or ""),
                    value=value,
                    value_type="vector group",
                    importable=False,
                    patch_path=f"physics_tuning.groups[{group_index}].slot_vector_groups",
                    editor_tab="Structured Editor",
                    record_index=group.get("record_index"),
                    item_index=vector_group.get("item_index"),
                    confidence=str(vector_group.get("confidence") or group.get("confidence") or "experimental"),
                    edit_risk=str(vector_group.get("edit_risk") or "high"),
                    effect=str(vector_group.get("likely_role") or category),
                    explanation=str(vector_group.get("description") or "Grouped adjacent float slots for readability."),
                    safe_edit_hint="Read-only grouping row. Edit the individual component rows below if you need to patch values.",
                    value_constraints="grouping metadata ignored on import; fixed-size component edits only",
                    source="physics_tuning",
                    viewer_selection_id=group_viewer_selection_id,
                    **{
                        **group_context_kwargs,
                        "display_label": f"{group_owner_label}: {vector_group.get('name') or 'vector'}",
                        "identity_path": (
                            f"{group_context_kwargs.get('identity_path')} -> {vector_group.get('name') or 'vector'}"
                            if group_context_kwargs.get("identity_path")
                            else f"record {group.get('record_index')} -> {vector_group.get('name') or 'vector'}"
                        ),
                    },
                )
            for slot_index, slot in enumerate(group.get("slots", []) if isinstance(group.get("slots"), list) else []):
                if not isinstance(slot, Mapping):
                    continue
                try:
                    item_index = int(slot.get("item_index"))
                    offset = int(slot.get("offset"))
                except (TypeError, ValueError):
                    item_index = None
                    offset = None
                _hkx_editor_add_row(
                    rows_by_group,
                    target_group,
                    label=f"{group_owner_label}: {slot.get('name') or slot_index}",
                    subject=str(group_owner_label or group.get("type_name") or ""),
                    field=str(slot.get("name") or ""),
                    value=slot.get("value"),
                    value_type="float32",
                    importable=True,
                    patch_path=f"physics_tuning.groups[{group_index}].slots[{slot_index}]",
                    editor_tab="Structured Editor",
                    record_index=group.get("record_index"),
                    item_index=item_index,
                    offset=offset,
                    confidence=str(slot.get("confidence") or group.get("confidence") or "experimental"),
                    edit_risk=str(slot.get("edit_risk") or ""),
                    effect=str(slot.get("plain_language_effect") or category),
                    explanation=str(slot.get("description") or group.get("description") or ""),
                    if_increased=str(slot.get("if_increased") or ""),
                    if_decreased=str(slot.get("if_decreased") or ""),
                    safe_edit_hint=str(slot.get("safe_edit_hint") or ""),
                    value_constraints=str(slot.get("value_constraints") or ""),
                    source="physics_tuning",
                    viewer_selection_id=group_viewer_selection_id,
                    **{
                        **group_context_kwargs,
                        "display_label": f"{group_owner_label}: {slot.get('name') or slot_index}",
                        "identity_path": (
                            f"{group_context_kwargs.get('identity_path')} -> {slot.get('name') or slot_index}"
                            if group_context_kwargs.get("identity_path")
                            else f"record {group.get('record_index')} item {item_index} offset {offset}"
                        ),
                    },
                )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Sequence',
    '_hkx_editor_add_row',
    '_hkx_editor_selection_id',
)
def _hkx_editor_add_object_rows(rows_by_group: Dict[str, List[Dict[str, object]]], objects: Sequence[Mapping[str, object]]) -> None:
    for object_info in objects:
        if not isinstance(object_info, Mapping):
            continue
        _hkx_editor_add_row(
            rows_by_group,
            "object_records",
            label=f"record {object_info.get('record_index')}: {object_info.get('type_name') or ''}",
            subject=str(object_info.get("type_name") or ""),
            value=f"{object_info.get('byte_length') or 0} bytes; status={object_info.get('status') or 'raw'}",
            value_type="object",
            record_index=object_info.get("record_index"),
            confidence=str(object_info.get("confidence") or object_info.get("status") or "raw"),
            explanation=str(object_info.get("description") or "Decoded or preserved ITEM object record."),
            source="objects",
            viewer_selection_id=_hkx_editor_selection_id("record", object_info.get("record_index")),
            context_label=str(object_info.get("type_name") or ""),
            display_label=f"record {object_info.get('record_index')}",
        )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Sequence',
    '_hkx_editor_add_row',
    '_hkx_editor_selection_id',
)
def _hkx_editor_add_raw_rows(rows_by_group: Dict[str, List[Dict[str, object]]], advanced_payloads: Sequence[Mapping[str, object]]) -> None:
    for payload in advanced_payloads:
        if not isinstance(payload, Mapping):
            continue
        if isinstance(payload.get("editable_values"), Mapping):
            continue
        _hkx_editor_add_row(
            rows_by_group,
            "raw_preserved_data",
            label=f"record {payload.get('record_index')}: {payload.get('type_name') or ''}",
            subject=str(payload.get("type_name") or ""),
            value=f"{payload.get('byte_length') or 0} bytes",
            value_type="raw_hex",
            record_index=payload.get("record_index"),
            confidence="raw",
            explanation=str(payload.get("description") or "Raw payload bytes preserved for byte-identical no-edit round-trip."),
            source="advanced_record_payloads",
            viewer_selection_id=_hkx_editor_selection_id("record", payload.get("record_index")),
            context_label=str(payload.get("type_name") or ""),
            display_label=f"record {payload.get('record_index')}",
        )
