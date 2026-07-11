from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'List',
    'Mapping',
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
    '_hkx_graph_record_node',
    '_hkx_graph_shape_viewer_id_from_path',
    '_hkx_graph_viewer_id',
)
def _hkx_graph_add_catalog(nodes, node_ids, edges, edge_ids, editable_field_catalog, constraint_owner_by_record_slot, tuning_owner_by_record, patch_by_shape_index, patch_by_record_item_offset):
    if isinstance(editable_field_catalog, Mapping):
        fields = editable_field_catalog.get("fields")
        for field_index, field in enumerate(fields if isinstance(fields, list) else []):
            if not isinstance(field, Mapping):
                continue
            shape_index = field.get("shape_index")
            record_index = field.get("record_index")
            item_index = field.get("item_index")
            offset = field.get("offset")
            field_name = str(field.get("name") or field.get("field") or f"value {field_index}")
            viewer_selection_id = ""
            owner_id = ""
            owner_relation = "has_editable_value"
            if shape_index not in (None, ""):
                owner_id = f"shape:{shape_index}"
                viewer_selection_id = _hkx_graph_viewer_id("shape", shape_index)
            elif (str(record_index), str(item_index), str(offset)) in constraint_owner_by_record_slot:
                owner_id = constraint_owner_by_record_slot[(str(record_index), str(item_index), str(offset))]
                viewer_selection_id = owner_id.replace(":", "/")
            elif record_index not in (None, "") and str(record_index) in tuning_owner_by_record:
                owner_id = tuning_owner_by_record[str(record_index)]
                viewer_selection_id = _hkx_graph_viewer_id("record", record_index)
            elif record_index not in (None, ""):
                owner_id = _hkx_graph_record_node(record_index)
                viewer_selection_id = _hkx_graph_viewer_id("record", record_index)
                owner_relation = "record_editable_value"
            if not owner_id:
                continue
            value_id = f"value:catalog:{field_index}"
            identity_bits = [
                owner_id.replace(":", "/"),
                field_name,
            ]
            if record_index not in (None, ""):
                identity_bits.append(f"record {record_index}")
            if item_index not in (None, ""):
                identity_bits.append(f"item {item_index}")
            if offset not in (None, ""):
                identity_bits.append(f"offset {field.get('hex_offset') or offset}")
            identity_path = " -> ".join(identity_bits)
            _hkx_graph_add_node(
                nodes,
                node_ids,
                value_id,
                "editable_value",
                field_name,
                category=field.get("category"),
                subject=field.get("subject"),
                field=field_name,
                value=field.get("value_summary"),
                record_index=record_index,
                item_index=item_index,
                offset=offset,
                hex_offset=field.get("hex_offset"),
                shape_index=shape_index,
                shape_type=field.get("shape_type"),
                value_type=field.get("value_type") or "fixed-size value",
                confidence=field.get("confidence"),
                edit_risk=field.get("edit_risk"),
                effect=field.get("effect"),
                editor_tab=field.get("editor_tab"),
                importable=field.get("importable"),
                viewer_selection_id=viewer_selection_id,
                identity_path=identity_path,
            )
            _hkx_graph_add_edge(
                edges,
                edge_ids,
                owner_id,
                value_id,
                owner_relation,
                confidence=field.get("confidence"),
                viewer_selection_id=viewer_selection_id,
                identity_path=identity_path,
                description="Editable field catalog links this owner to a routed editor value.",
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
                    hex_offset=field.get("hex_offset"),
                    confidence=field.get("confidence"),
                    viewer_selection_id=viewer_selection_id,
                    identity_path=identity_path,
                    link_evidence="exact",
                )
            patch_matches: List[Mapping[str, object]] = []
            if shape_index not in (None, ""):
                path_prefix = f"shapes[{shape_index}].{field_name}"
                patch_matches = [
                    patch
                    for patch in patch_by_shape_index.get(str(shape_index), [])
                    if str(patch.get("path") or "").startswith(path_prefix) or str(patch.get("name") or "") == field_name
                ]
            elif record_index not in (None, "") and item_index not in (None, "") and offset not in (None, ""):
                patch_matches = patch_by_record_item_offset.get((str(record_index), str(item_index), str(offset)), [])
            for patch in patch_matches[:24]:
                patch_id = f"patch:{patch.get('index')}"
                _hkx_graph_add_edge(
                    edges,
                    edge_ids,
                    value_id,
                    patch_id,
                    "writes_byte_offset",
                    record_index=patch.get("record_index") or record_index,
                    item_index=patch.get("item_index") or item_index,
                    offset=offset,
                    hex_offset=field.get("hex_offset") or patch.get("hex_relative_offset"),
                    hex_absolute_data_offset=patch.get("hex_absolute_data_offset"),
                    byte_size=patch.get("byte_size"),
                    value_type=patch.get("value_type"),
                    confidence=patch.get("confidence") or field.get("confidence"),
                    viewer_selection_id=viewer_selection_id or _hkx_graph_shape_viewer_id_from_path(patch.get("path")),
                    identity_path=f"{identity_path} -> {patch.get('hex_absolute_data_offset') or patch_id}",
                    description="Editable field is backed by this fixed byte patch target.",
                    link_evidence="exact",
                )


@bind_archive_hkx_globals(
    '_hkx_graph_add_edge',
    '_hkx_graph_add_node',
)
def _hkx_graph_add_descriptors(nodes, node_ids, edges, edge_ids, descriptor_hints, file_id):
    for descriptor_index, descriptor in enumerate(descriptor_hints):
        descriptor_id = f"descriptor:{descriptor_index}"
        _hkx_graph_add_node(nodes, node_ids, descriptor_id, "descriptor_xml", str(descriptor.get("path") or descriptor.get("stem") or descriptor_id), root_tag=descriptor.get("root_tag"))
        _hkx_graph_add_edge(edges, edge_ids, file_id, descriptor_id, "related_context", link_evidence="inferred")
