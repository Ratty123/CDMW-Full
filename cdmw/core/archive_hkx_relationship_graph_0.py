from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    're',
)
def _hkx_graph_text_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


@bind_archive_hkx_globals(
    '_hkx_editor_selection_id',
)
def _hkx_graph_viewer_id(kind: str, index: object) -> str:
    return _hkx_editor_selection_id(kind, index)


@bind_archive_hkx_globals()
def _hkx_graph_record_node(record_index: object) -> str:
    return f"record:{record_index}" if record_index not in (None, "") else ""


@bind_archive_hkx_globals(
    '_hkx_graph_viewer_id',
    're',
)
def _hkx_graph_shape_viewer_id_from_path(path: object) -> str:
    match = re.search(r"shapes\[(\d+)\]", str(path or ""))
    return _hkx_graph_viewer_id("shape", match.group(1)) if match else ""


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_graph_patch_identity_path(entry: Mapping[str, object]) -> str:
    parts = [str(entry.get("path") or "byte patch")]
    record_index = entry.get("record_index")
    if record_index not in (None, ""):
        parts.append(f"record {record_index}")
    if entry.get("hex_absolute_data_offset") not in (None, ""):
        parts.append(str(entry.get("hex_absolute_data_offset")))
    return " -> ".join(parts)


@bind_archive_hkx_globals(
    'Dict',
    'List',
    '_hkx_graph_text_key',
)
def _hkx_graph_register_body_key(body_ids_by_key: Dict[str, List[str]], body_id: str, value: object) -> None:
    key = _hkx_graph_text_key(value)
    if key and body_id not in body_ids_by_key[key]:
        body_ids_by_key[key].append(body_id)


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Tuple',
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
    '_hkx_graph_patch_identity_path',
    '_hkx_graph_shape_viewer_id_from_path',
    'defaultdict',
    're',
)
def _hkx_graph_build_patch_indexes(nodes, node_ids, edges, edge_ids, byte_patch_map, payload_summary_by_record):
    patch_by_shape_index: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    patch_by_record_item_offset: Dict[Tuple[str, str, str], List[Mapping[str, object]]] = defaultdict(list)
    patch_by_record: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    if isinstance(byte_patch_map, Mapping):
        for entry in byte_patch_map.get("entries", []) if isinstance(byte_patch_map.get("entries"), list) else []:
            if not isinstance(entry, Mapping):
                continue
            patch_id = f"patch:{entry.get('index')}"
            patch_path = str(entry.get("path") or "")
            record_index = entry.get("record_index")
            if record_index not in (None, ""):
                patch_by_record[str(record_index)].append(entry)
            viewer_selection_id = _hkx_graph_shape_viewer_id_from_path(patch_path)
            shape_match = re.search(r"shapes\[(\d+)\]", patch_path)
            if shape_match:
                patch_by_shape_index[shape_match.group(1)].append(entry)
            item_index = entry.get("item_index")
            relative_offset = entry.get("relative_offset")
            if record_index not in (None, "") and item_index not in (None, "") and isinstance(relative_offset, int):
                payload_summary = payload_summary_by_record.get(int(record_index)) if isinstance(record_index, int) else None
                stride_value = payload_summary.inferred_stride if payload_summary is not None else None
                try:
                    stride = int(stride_value) if stride_value is not None and abs(float(stride_value) - int(float(stride_value))) < 0.001 else 0
                    item_int = int(item_index)
                    local_offset = int(relative_offset) - item_int * stride if stride > 0 else int(relative_offset)
                except (TypeError, ValueError, OverflowError):
                    local_offset = -1
                if local_offset >= 0:
                    patch_by_record_item_offset[(str(record_index), str(item_index), str(local_offset))].append(entry)
            _hkx_graph_add_node(
                nodes,
                node_ids,
                patch_id,
                "byte_patch_target",
                str(patch_path or patch_id),
                category=entry.get("category"),
                name=entry.get("name"),
                subject=entry.get("subject"),
                record_index=entry.get("record_index"),
                item_index=entry.get("item_index"),
                row_index=entry.get("row_index"),
                component=entry.get("component"),
                relative_offset=entry.get("relative_offset"),
                hex_relative_offset=entry.get("hex_relative_offset"),
                absolute_data_offset=entry.get("absolute_data_offset"),
                hex_absolute_data_offset=entry.get("hex_absolute_data_offset"),
                byte_size=entry.get("byte_size"),
                value_type=entry.get("value_type"),
                confidence=entry.get("confidence"),
                effect=entry.get("effect"),
                viewer_selection_id=viewer_selection_id,
                identity_path=_hkx_graph_patch_identity_path(entry),
                link_evidence="exact",
            )
            if record_index not in (None, ""):
                _hkx_graph_add_edge(
                    edges,
                    edge_ids,
                    patch_id,
                    f"record:{record_index}",
                    "writes_bytes",
                    record_index=record_index,
                    item_index=entry.get("item_index"),
                    offset=entry.get("relative_offset"),
                    hex_offset=entry.get("hex_relative_offset"),
                    hex_absolute_data_offset=entry.get("hex_absolute_data_offset"),
                    byte_size=entry.get("byte_size"),
                    value_type=entry.get("value_type"),
                    confidence=entry.get("confidence"),
                    viewer_selection_id=viewer_selection_id,
                    identity_path=_hkx_graph_patch_identity_path(entry),
                    link_evidence="exact",
                )
    return patch_by_shape_index, patch_by_record_item_offset, patch_by_record


@bind_archive_hkx_globals(
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
)
def _hkx_graph_add_sections_and_records(nodes, node_ids, edges, edge_ids, summary, file_id):
    for section in summary.tag_items:
        node_id = f"section:{section.name}"
        _hkx_graph_add_node(
            nodes,
            node_ids,
            node_id,
            "tag_section",
            section.name,
            offset=section.offset,
            declared_length=section.declared_length,
        )
        _hkx_graph_add_edge(edges, edge_ids, file_id, node_id, "contains", link_evidence="exact")
    for record in summary.item_records:
        node_id = f"record:{record.index}"
        _hkx_graph_add_node(
            nodes,
            node_ids,
            node_id,
            "item_record",
            f"{record.index}: {record.type_name}",
            record_index=record.index,
            type_index=record.type_index,
            type_name=record.type_name,
            count=record.count,
            data_offset=record.data_offset,
        )
        _hkx_graph_add_edge(edges, edge_ids, "section:ITEM", node_id, "indexes", link_evidence="exact")


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_graph_add_edge',
)
def _hkx_graph_add_native_edges(edges, edge_ids, summary, record_type_by_index):
    reference_edge_count = 0
    fixup_backed_reference_edge_count = 0
    native_graph = summary.native_model_graph if isinstance(summary.native_model_graph, Mapping) else {}
    native_edges = native_graph.get("edges") if isinstance(native_graph, Mapping) else None
    if isinstance(native_edges, list):
        for native_edge in native_edges[:3000]:
            if not isinstance(native_edge, Mapping):
                continue
            source_id = str(native_edge.get("source") or "")
            target_id = str(native_edge.get("target") or "")
            relation = str(native_edge.get("relation") or "native_reference")
            if not source_id or not target_id:
                continue
            resolution_source = str(native_edge.get("resolution_source") or "")
            reference_category = str(native_edge.get("reference_category") or "")
            link_evidence = (
                "fixup_backed"
                if resolution_source == "ptch"
                else "declared_owner_array"
                if reference_category == "array_data_reference"
                else "typed_layout"
                if resolution_source == "typed_layout"
                else "inferred"
                if resolution_source == "inferred_offset"
                else "raw_observation"
            )
            source_record_index = native_edge.get("source_record_index")
            target_record_index = native_edge.get("target_record_index")
            source_type = record_type_by_index.get(source_record_index) if isinstance(source_record_index, int) else ""
            target_type = record_type_by_index.get(target_record_index) if isinstance(target_record_index, int) else ""
            owner_local_offset = native_edge.get("owner_local_offset")
            _hkx_graph_add_edge(
                edges,
                edge_ids,
                source_id,
                target_id,
                relation,
                record_index=source_record_index,
                target_record_index=target_record_index,
                owner_field=native_edge.get("owner_field_name"),
                offset=owner_local_offset,
                hex_offset=f"0x{owner_local_offset:X}" if isinstance(owner_local_offset, int) else "",
                reference_category=reference_category,
                reference_source=resolution_source or "native_model_graph",
                source_type=source_type,
                target_type=target_type,
                confidence=native_edge.get("confidence") or "experimental",
                description=(
                    "Native graph edge recovered from PTCH/fixup data."
                    if link_evidence == "fixup_backed"
                    else "Native graph edge recovered from owner-array context."
                    if link_evidence == "declared_owner_array"
                    else "Native graph edge recovered from decoded object layout."
                ),
                link_evidence=link_evidence,
            )
            reference_edge_count += 1
            if link_evidence == "fixup_backed":
                fixup_backed_reference_edge_count += 1
    native_owner_arrays = native_graph.get("owner_arrays") if isinstance(native_graph, Mapping) else None
    if isinstance(native_owner_arrays, list):
        for owner_array in native_owner_arrays[:1000]:
            if not isinstance(owner_array, Mapping):
                continue
            owner_record_index = owner_array.get("owner_record_index")
            target_record_index = owner_array.get("target_record_index")
            if not isinstance(owner_record_index, int) or not isinstance(target_record_index, int):
                continue
            field_name = str(owner_array.get("field_name") or "owner_array")
            _hkx_graph_add_edge(
                edges,
                edge_ids,
                f"record:{owner_record_index}",
                f"record:{target_record_index}",
                f"owner_array:{field_name}",
                record_index=owner_record_index,
                target_record_index=target_record_index,
                owner_field=field_name,
                offset=owner_array.get("owner_local_offset"),
                reference_category="array_data_reference",
                reference_source=owner_array.get("resolution_source") or "native_owner_array",
                array_type=owner_array.get("array_type"),
                element_type=owner_array.get("element_type"),
                numelements=owner_array.get("numelements"),
                confidence=owner_array.get("confidence") or "strong inference",
                description="Native owner-array mapping recovered from fixup/data pointer context.",
                link_evidence="declared_owner_array",
            )
            reference_edge_count += 1
    return reference_edge_count, fixup_backed_reference_edge_count


@bind_archive_hkx_globals(
    'Mapping',
    'Optional',
    '_hkx_graph_add_edge',
    '_hkx_relationship_link_evidence',
    '_hkx_semantic_record_relation',
)
def _hkx_graph_add_object_edges(edges, edge_ids, objects, record_type_by_index):
    reference_edge_count = 0
    fixup_backed_reference_edge_count = 0
    for object_info in objects:
        if not isinstance(object_info, Mapping):
            continue
        record_index = object_info.get("record_index")
        if not isinstance(record_index, int):
            continue
        references = object_info.get("references")
        if not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            target_record_index = reference.get("target_record_index")
            if not isinstance(target_record_index, int):
                continue
            relation = str(reference.get("reference_kind") or "possible_reference")
            link_evidence = _hkx_relationship_link_evidence(reference, relation)
            _hkx_graph_add_edge(
                edges,
                edge_ids,
                f"record:{record_index}",
                f"record:{target_record_index}",
                relation,
                offset=reference.get("offset"),
                hex_offset=reference.get("hex_offset"),
                raw_value=reference.get("raw_value"),
                raw_value_hex=reference.get("raw_value_hex"),
                reference_category=reference.get("reference_category"),
                confidence=reference.get("confidence") or "experimental",
                description=reference.get("description"),
                link_evidence=link_evidence,
            )
            reference_edge_count += 1
            if str(reference.get("reference_source") or reference.get("reference_category") or "").casefold().startswith(("ptch", "fixup")):
                fixup_backed_reference_edge_count += 1
            semantic_relation = _hkx_semantic_record_relation(
                str(object_info.get("type_name") or ""),
                str(reference.get("target_type_name") or ""),
                relation,
            )
            if semantic_relation is not None:
                semantic_name, semantic_description = semantic_relation
                _hkx_graph_add_edge(
                    edges,
                    edge_ids,
                    f"record:{record_index}",
                    f"record:{target_record_index}",
                    semantic_name,
                    offset=reference.get("offset"),
                    hex_offset=reference.get("hex_offset"),
                    raw_value=reference.get("raw_value"),
                    raw_relation=relation,
                    confidence="experimental",
                    description=semantic_description,
                    link_evidence=link_evidence if link_evidence == "fixup_backed" else "inferred",
                )
        layout = object_info.get("layout")
        fields = layout.get("fields") if isinstance(layout, Mapping) else None
        if not isinstance(fields, list):
            continue
        source_type_name = str(object_info.get("type_name") or "")
        for field in fields:
            if not isinstance(field, Mapping):
                continue
            value = field.get("value")
            if not isinstance(value, Mapping):
                continue
            target_record_index: Optional[int] = None
            relation = "possible_record_index_reference"
            description = "A decoded layout field contains a small integer that matches an ITEM record index."
            if source_type_name == "HavokShapeNameProperty" and isinstance(value.get("candidate_char_record_index"), int):
                target_record_index = int(value["candidate_char_record_index"])
                relation = "possible_shape_name_text"
                description = "Shape-name property likely points to a char/string record containing the body or shape label."
            elif source_type_name == "hkaSkeletonMapper" and isinstance(value.get("data_or_reference"), int):
                target_record_index = int(value["data_or_reference"])
                target_type = record_type_by_index.get(target_record_index, "")
                if target_type == "hkSkeleton":
                    relation = "possible_mapper_skeleton"
                    description = "Skeleton mapper header likely references one side of the source/target skeleton pair."
                elif target_type == "hkaSkeletonMapperData::SimpleMapping":
                    relation = "possible_mapper_simple_mapping"
                    description = "Skeleton mapper header likely references its compact SimpleMapping table."
                else:
                    relation = "possible_mapper_record"
                    description = "Skeleton mapper header contains a record-index-like value. Exact role is still inferred."
            elif source_type_name == "hkaAnimationContainer" and isinstance(value.get("data_or_reference"), int):
                target_record_index = int(value["data_or_reference"])
                relation = "possible_animation_container_record"
                description = "Animation container field contains a record-index-like value for a contained skeleton/animation object."
            if target_record_index is None or target_record_index not in record_type_by_index:
                continue
            _hkx_graph_add_edge(
                edges,
                edge_ids,
                f"record:{record_index}",
                f"record:{target_record_index}",
                relation,
                offset=field.get("offset"),
                hex_offset=field.get("hex_offset"),
                raw_value=target_record_index,
                confidence=field.get("confidence") or "experimental",
                description=description,
            )
    return reference_edge_count, fixup_backed_reference_edge_count


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_editable_shape_subject',
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
)
def _hkx_graph_add_shapes(nodes, node_ids, edges, edge_ids, shapes):
    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        shape_index = shape.get("index")
        shape_id = f"shape:{shape_index}"
        _hkx_graph_add_node(
            nodes,
            node_ids,
            shape_id,
            "collision_shape",
            f"{shape.get('shape_type') or 'shape'} {shape_index}",
            shape_index=shape_index,
            shape_type=shape.get("shape_type"),
            subject=_hkx_editable_shape_subject(shape),
        )
        record_index = shape.get("shape_record_index")
        if isinstance(record_index, int):
            _hkx_graph_add_edge(edges, edge_ids, shape_id, f"record:{record_index}", "decoded_from", link_evidence="exact")
        records = shape.get("records")
        if isinstance(records, Mapping):
            for name, record_value in records.items():
                if isinstance(record_value, int):
                    _hkx_graph_add_edge(edges, edge_ids, shape_id, f"record:{record_value}", f"uses_{name}", link_evidence="inferred")


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    '_hkx_editor_selection_id',
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
    '_hkx_graph_register_body_key',
    '_hkx_graph_viewer_id',
    'defaultdict',
)
def _hkx_graph_add_bodies(nodes, node_ids, edges, edge_ids, physics_body_summary, physics_body_context):
    body_ids_by_key: Dict[str, List[str]] = defaultdict(list)
    if isinstance(physics_body_summary, Mapping):
        for body in physics_body_summary.get("bodies", []) if isinstance(physics_body_summary.get("bodies"), list) else []:
            if not isinstance(body, Mapping):
                continue
            body_index = body.get("index")
            body_id = f"body:{body_index}"
            shape_index = body.get("shape_index")
            viewer_selection_id = _hkx_graph_viewer_id("shape", shape_index) if shape_index not in (None, "") else ""
            body_name = str(body.get("body_name") or body.get("socket_name") or body_id)
            material_name = str(body.get("physics_material_name") or "").strip()
            descriptor_contexts = body.get("descriptor_contexts")
            if isinstance(descriptor_contexts, list):
                for context in descriptor_contexts:
                    if not isinstance(context, Mapping):
                        continue
                    if not material_name and str(context.get("physics_material_name") or "").strip():
                        material_name = str(context.get("physics_material_name") or "").strip()
            identity_path = " -> ".join(
                part
                for part in (
                    f"body:{body_name}",
                    f"shape/{shape_index}" if shape_index not in (None, "") else "",
                    f"material:{material_name}" if material_name else "",
                )
                if part
            )
            _hkx_graph_add_node(
                nodes,
                node_ids,
                body_id,
                "body",
                body_name,
                body_index=body_index,
                shape_index=shape_index,
                shape_type=body.get("shape_type"),
                simulation_role=body.get("simulation_role"),
                socket_name=body.get("socket_name"),
                fixed_socket_name=body.get("fixed_socket_name"),
                physics_material_name=material_name,
                confidence=body.get("confidence"),
                viewer_selection_id=viewer_selection_id,
                identity_path=identity_path,
            )
            for key_name in ("body_name", "socket_name", "fixed_socket_name"):
                _hkx_graph_register_body_key(body_ids_by_key, body_id, body.get(key_name))
            if isinstance(descriptor_contexts, list):
                for context in descriptor_contexts:
                    if not isinstance(context, Mapping):
                        continue
                    for key_name in ("body_name", "socket_name", "fixed_socket_name"):
                        _hkx_graph_register_body_key(body_ids_by_key, body_id, context.get(key_name))
            if shape_index not in (None, ""):
                _hkx_graph_add_edge(
                    edges,
                    edge_ids,
                    body_id,
                    f"shape:{shape_index}",
                    "body_shape",
                    confidence=body.get("confidence"),
                    viewer_selection_id=viewer_selection_id,
                    identity_path=identity_path,
                    description="Body summary links this body/context row to the decoded collision shape.",
                    link_evidence="inferred",
                )
            if material_name:
                material_id = f"material:{_hkx_editor_selection_id(material_name)}"
                _hkx_graph_add_node(
                    nodes,
                    node_ids,
                    material_id,
                    "material",
                    material_name,
                    physics_material_name=material_name,
                    confidence=body.get("confidence") or "descriptor_context",
                    viewer_selection_id=viewer_selection_id,
                    identity_path=f"{identity_path} -> material:{material_name}" if identity_path else f"material:{material_name}",
                )
                _hkx_graph_add_edge(
                    edges,
                    edge_ids,
                    body_id,
                    material_id,
                    "uses_material",
                    confidence=body.get("confidence") or "descriptor_context",
                    viewer_selection_id=viewer_selection_id,
                    identity_path=f"{identity_path} -> material:{material_name}" if identity_path else f"material:{material_name}",
                    description="Descriptor/body context links this body to a material or simulation material name.",
                    link_evidence="inferred",
                )
            records = body.get("records")
            if isinstance(records, Mapping):
                for record_role, record_value in records.items():
                    if isinstance(record_value, int):
                        _hkx_graph_add_edge(
                            edges,
                            edge_ids,
                            body_id,
                            f"record:{record_value}",
                            f"body_uses_{record_role}",
                            confidence=body.get("confidence"),
                            viewer_selection_id=viewer_selection_id,
                            identity_path=identity_path,
                            link_evidence="inferred",
                        )
    if isinstance(physics_body_context, Mapping):
        for body_index, body in enumerate(physics_body_context.get("body_contexts", []) if isinstance(physics_body_context.get("body_contexts"), list) else []):
            if not isinstance(body, Mapping):
                continue
            body_id = f"body:{body_index}"
            _hkx_graph_add_node(nodes, node_ids, body_id, "body", str(body.get("body_name") or f"body {body_index}"), socket_name=body.get("socket_name"), simulation_role=body.get("simulation_role"))
            for key_name in ("body_name", "socket_name", "fixed_socket_name"):
                _hkx_graph_register_body_key(body_ids_by_key, body_id, body.get(key_name))
            for match in body.get("shape_matches", []) if isinstance(body.get("shape_matches"), list) else []:
                if isinstance(match, Mapping) and match.get("decoded_shape_index") is not None:
                    shape_index = match.get("decoded_shape_index")
                    _hkx_graph_add_edge(
                        edges,
                        edge_ids,
                        body_id,
                        f"shape:{shape_index}",
                        "matches_shape",
                        confidence=match.get("confidence"),
                        viewer_selection_id=_hkx_graph_viewer_id("shape", shape_index),
                        identity_path=f"body:{body.get('body_name') or body_index} -> shape/{shape_index}",
                        link_evidence="inferred",
                    )
    return body_ids_by_key


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
)
def _hkx_graph_tuning_owner_map(physics_tuning):
    tuning_owner_by_record: Dict[str, str] = {}
    if isinstance(physics_tuning, Mapping):
        for group_index, group in enumerate(physics_tuning.get("groups", []) if isinstance(physics_tuning.get("groups"), list) else []):
            if isinstance(group, Mapping) and group.get("record_index") not in (None, ""):
                tuning_owner_by_record[str(group.get("record_index"))] = f"tuning:{group_index}"
    return tuning_owner_by_record


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Tuple',
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
    '_hkx_graph_text_key',
    '_hkx_graph_viewer_id',
)
def _hkx_graph_add_constraints(nodes, node_ids, edges, edge_ids, physics_constraint_summary, body_ids_by_key, patch_by_record_item_offset):
    constraint_owner_by_record_slot: Dict[Tuple[str, str, str], str] = {}
    if isinstance(physics_constraint_summary, Mapping):
        for constraint in physics_constraint_summary.get("constraints", []) if isinstance(physics_constraint_summary.get("constraints"), list) else []:
            if not isinstance(constraint, Mapping):
                continue
            constraint_index = constraint.get("index")
            constraint_id = f"constraint:{constraint_index}"
            viewer_selection_id = _hkx_graph_viewer_id("constraint", constraint_index)
            constraint_name = str(constraint.get("name") or constraint_id)
            _hkx_graph_add_node(
                nodes,
                node_ids,
                constraint_id,
                "constraint",
                constraint_name,
                type_name=constraint.get("type_name"),
                confidence=constraint.get("confidence"),
                viewer_selection_id=viewer_selection_id,
                identity_path=f"constraint/{constraint_index}:{constraint_name}",
            )
            for key, relation in (("constraint_record_index", "decoded_from"), ("motor_record_index", "uses_motor")):
                record_index = constraint.get(key)
                if record_index not in (None, ""):
                    _hkx_graph_add_edge(
                        edges,
                        edge_ids,
                        constraint_id,
                        f"record:{record_index}",
                        relation,
                        record_index=record_index,
                        viewer_selection_id=viewer_selection_id,
                        identity_path=f"constraint/{constraint_index}:{constraint_name} -> record {record_index}",
                        link_evidence="exact" if relation == "decoded_from" else "inferred",
                    )
            descriptor_context = constraint.get("descriptor_context")
            if isinstance(descriptor_context, Mapping):
                body_keys = [
                    _hkx_graph_text_key(descriptor_context.get(key_name))
                    for key_name in ("body_name", "socket_name", "fixed_socket_name")
                    if _hkx_graph_text_key(descriptor_context.get(key_name))
                ]
                linked_body_ids: List[str] = []
                for body_key in body_keys:
                    for body_id in body_ids_by_key.get(body_key, []):
                        if body_id not in linked_body_ids:
                            linked_body_ids.append(body_id)
                for body_id in linked_body_ids[:4]:
                    _hkx_graph_add_edge(
                        edges,
                        edge_ids,
                        constraint_id,
                        body_id,
                        "constraint_body_context",
                        confidence=descriptor_context.get("confidence") or "descriptor_context",
                        viewer_selection_id=viewer_selection_id,
                        identity_path=f"constraint/{constraint_index}:{constraint_name} -> {body_id}",
                        description="Descriptor context names the body/socket this constraint is likely attached to.",
                        link_evidence="inferred",
                    )
            for slot_group_name, slot_source, record_key in (
                ("constraint_slots", "constraint", "constraint_record_index"),
                ("motor_slots", "motor", "motor_record_index"),
            ):
                slots = constraint.get(slot_group_name)
                if not isinstance(slots, list):
                    continue
                record_index = constraint.get(record_key)
                for slot in slots:
                    if not isinstance(slot, Mapping):
                        continue
                    item_index = slot.get("item_index")
                    offset = slot.get("offset")
                    if item_index in (None, "") or offset in (None, ""):
                        continue
                    value_id = f"value:constraint:{constraint_index}:{slot_source}:{item_index}:{offset}"
                    slot_name = str(slot.get("name") or f"{slot_source} slot")
                    constraint_owner_by_record_slot[(str(record_index), str(item_index), str(offset))] = constraint_id
                    identity_path = f"constraint/{constraint_index}:{constraint_name} -> {slot_name} -> record {record_index} item {item_index} offset {slot.get('hex_offset') or offset}"
                    _hkx_graph_add_node(
                        nodes,
                        node_ids,
                        value_id,
                        "editable_value",
                        slot_name,
                        category="constraint_motor",
                        field=slot_name,
                        value=slot.get("value"),
                        record_index=record_index,
                        item_index=item_index,
                        offset=offset,
                        hex_offset=slot.get("hex_offset"),
                        value_type="float32",
                        confidence=slot.get("confidence"),
                        editor_tab="Structured Editor",
                        importable=True,
                        viewer_selection_id=viewer_selection_id,
                        identity_path=identity_path,
                    )
                    _hkx_graph_add_edge(
                        edges,
                        edge_ids,
                        constraint_id,
                        value_id,
                        "has_editable_value",
                        confidence=slot.get("confidence"),
                        viewer_selection_id=viewer_selection_id,
                        identity_path=identity_path,
                        description="Constraint/motor slot exposed as a fixed-size editable value.",
                        link_evidence="exact",
                    )
                    if record_index not in (None, ""):
                        _hkx_graph_add_edge(
                            edges,
                            edge_ids,
                            value_id,
                            f"record:{record_index}",
                            "patches_record",
                            record_index=record_index,
                            item_index=item_index,
                            offset=offset,
                            hex_offset=slot.get("hex_offset"),
                            confidence=slot.get("confidence"),
                            viewer_selection_id=viewer_selection_id,
                            identity_path=identity_path,
                            link_evidence="exact",
                        )
                    for patch in patch_by_record_item_offset.get((str(record_index), str(item_index), str(offset)), [])[:8]:
                        patch_id = f"patch:{patch.get('index')}"
                        _hkx_graph_add_edge(
                            edges,
                            edge_ids,
                            value_id,
                            patch_id,
                            "writes_byte_offset",
                            record_index=record_index,
                            item_index=item_index,
                            offset=offset,
                            hex_offset=slot.get("hex_offset"),
                            hex_absolute_data_offset=patch.get("hex_absolute_data_offset"),
                            byte_size=patch.get("byte_size"),
                            value_type=patch.get("value_type"),
                            confidence=patch.get("confidence") or slot.get("confidence"),
                            viewer_selection_id=viewer_selection_id,
                            identity_path=f"{identity_path} -> {patch.get('hex_absolute_data_offset') or patch_id}",
                            description="Editable value is backed by this fixed byte patch target.",
                            link_evidence="exact",
                        )
    return constraint_owner_by_record_slot


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
)
def _hkx_graph_add_tuning(nodes, node_ids, edges, edge_ids, physics_tuning):
    if isinstance(physics_tuning, Mapping):
        for group_index, group in enumerate(physics_tuning.get("groups", []) if isinstance(physics_tuning.get("groups"), list) else []):
            if not isinstance(group, Mapping):
                continue
            tuning_id = f"tuning:{group_index}"
            _hkx_graph_add_node(nodes, node_ids, tuning_id, "tuning_group", str(group.get("label") or group.get("category") or tuning_id), category=group.get("category"), type_name=group.get("type_name"))
            if group.get("record_index") is not None:
                _hkx_graph_add_edge(edges, edge_ids, tuning_id, f"record:{group.get('record_index')}", "patches_record", link_evidence="exact")
