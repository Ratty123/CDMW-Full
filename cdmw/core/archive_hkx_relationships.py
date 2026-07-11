from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxTagfileSummary',
    'List',
    'Mapping',
    'Optional',
    'Sequence',
    'Tuple',
    '_hkx_graph_add_bodies',
    '_hkx_graph_add_catalog',
    '_hkx_graph_add_constraints',
    '_hkx_graph_add_descriptors',
    '_hkx_graph_add_native_edges',
    '_hkx_graph_add_node',
    '_hkx_graph_add_object_edges',
    '_hkx_graph_add_sections_and_records',
    '_hkx_graph_add_shapes',
    '_hkx_graph_add_tuning',
    '_hkx_graph_build_patch_indexes',
    '_hkx_graph_tuning_owner_map',
)
def _hkx_relationship_graph_document(
    summary: HkxTagfileSummary,
    shapes: Sequence[Mapping[str, object]],
    objects: Sequence[Mapping[str, object]],
    physics_tuning: Optional[Mapping[str, object]],
    physics_body_context: Optional[Mapping[str, object]],
    physics_body_summary: Optional[Mapping[str, object]],
    physics_constraint_summary: Optional[Mapping[str, object]],
    editable_field_catalog: Optional[Mapping[str, object]],
    descriptor_hints: Sequence[Mapping[str, object]],
    byte_patch_map: Optional[Mapping[str, object]],
) -> Dict[str, object]:
    nodes: List[Dict[str, object]] = []
    edges: List[Dict[str, object]] = []
    node_ids: set[str] = set()
    edge_ids: set[Tuple[str, str, str]] = set()
    file_id = "file:hkx"
    _hkx_graph_add_node(nodes, node_ids, file_id, "file", "HKX file", sdk_version=summary.sdk_version)
    payload_summary_by_record = {item.record_index: item for item in summary.item_payload_summaries}
    patch_by_shape_index, patch_by_record_item_offset, _patch_by_record = _hkx_graph_build_patch_indexes(
        nodes, node_ids, edges, edge_ids, byte_patch_map, payload_summary_by_record
    )
    _hkx_graph_add_sections_and_records(nodes, node_ids, edges, edge_ids, summary, file_id)
    record_type_by_index = {record.index: record.type_name for record in summary.item_records}
    native_reference_count, fixup_backed_reference_edge_count = _hkx_graph_add_native_edges(
        edges, edge_ids, summary, record_type_by_index
    )
    object_reference_count, object_fixup_count = _hkx_graph_add_object_edges(
        edges, edge_ids, objects, record_type_by_index
    )
    reference_edge_count = native_reference_count + object_reference_count
    fixup_backed_reference_edge_count += object_fixup_count
    _hkx_graph_add_shapes(nodes, node_ids, edges, edge_ids, shapes)
    body_ids_by_key = _hkx_graph_add_bodies(
        nodes, node_ids, edges, edge_ids, physics_body_summary, physics_body_context
    )
    tuning_owner_by_record = _hkx_graph_tuning_owner_map(physics_tuning)
    constraint_owner_by_record_slot = _hkx_graph_add_constraints(
        nodes, node_ids, edges, edge_ids, physics_constraint_summary, body_ids_by_key, patch_by_record_item_offset
    )
    _hkx_graph_add_tuning(nodes, node_ids, edges, edge_ids, physics_tuning)
    _hkx_graph_add_catalog(
        nodes,
        node_ids,
        edges,
        edge_ids,
        editable_field_catalog,
        constraint_owner_by_record_slot,
        tuning_owner_by_record,
        patch_by_shape_index,
        patch_by_record_item_offset,
    )
    _hkx_graph_add_descriptors(nodes, node_ids, edges, edge_ids, descriptor_hints, file_id)
    identity_relations = {
        "body_shape",
        "matches_shape",
        "uses_material",
        "constraint_body_context",
        "has_editable_value",
        "record_editable_value",
        "patches_record",
        "writes_byte_offset",
        "writes_bytes",
    }
    identity_edge_count = sum(1 for edge in edges if str(edge.get("relation") or "") in identity_relations)
    byte_patch_edge_count = sum(1 for edge in edges if str(edge.get("relation") or "") in {"writes_byte_offset", "writes_bytes"})
    editable_value_node_count = sum(1 for node in nodes if str(node.get("kind") or "") == "editable_value")
    material_node_count = sum(1 for node in nodes if str(node.get("kind") or "") == "material")
    return {
        "status": "generated_from_current_decoder",
        "imported": False,
        "description": (
            "Best-effort graph for browsing HKX records, bodies, shapes, materials, constraints, editable values, "
            "and byte patch targets. Identity edges are for UI navigation only and are ignored on import."
        ),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "reference_edge_count": reference_edge_count,
        "fixup_backed_reference_edge_count": fixup_backed_reference_edge_count,
        "identity_edge_count": identity_edge_count,
        "editable_value_node_count": editable_value_node_count,
        "byte_patch_edge_count": byte_patch_edge_count,
        "material_node_count": material_node_count,
        "nodes": nodes,
        "edges": edges,
    }
