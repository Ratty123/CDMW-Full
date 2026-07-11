from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    'Optional',
    '_hkx_xml_add_biggest_hkclass_gate',
    '_hkx_xml_add_hard_decoder_targets',
    '_hkx_xml_add_hkclass_gui_readiness',
    '_hkx_xml_add_hkclass_import_safety',
    '_hkx_xml_add_hkclass_internals',
    '_hkx_xml_add_missing_hkclass_metadata',
    '_hkx_xml_add_native_model_graph_readiness',
    '_hkx_xml_add_no_edit_writer_readiness',
    '_hkx_xml_add_unresolved_hkclass_counts',
    '_hkx_xml_hkclass_readiness_element',
)
def _hkx_xml_add_hkclass_metadata_readiness(parent: ET.Element, readiness: object) -> Optional[ET.Element]:
    if not isinstance(readiness, Mapping):
        return None
    readiness_element = _hkx_xml_hkclass_readiness_element(parent, readiness)
    _hkx_xml_add_missing_hkclass_metadata(readiness_element, readiness)
    _hkx_xml_add_unresolved_hkclass_counts(readiness_element, readiness)
    _hkx_xml_add_native_model_graph_readiness(readiness_element, readiness)
    _hkx_xml_add_biggest_hkclass_gate(readiness_element, readiness)
    _hkx_xml_add_no_edit_writer_readiness(readiness_element, readiness)
    _hkx_xml_add_hkclass_internals(readiness_element, readiness)
    _hkx_xml_add_hard_decoder_targets(readiness_element, readiness)
    _hkx_xml_add_hkclass_gui_readiness(readiness_element, readiness)
    _hkx_xml_add_hkclass_import_safety(readiness_element, readiness)
    return readiness_element


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_mesh_detail_summary',
    '_hkx_xml_add_mesh_record_group',
    '_hkx_xml_mesh_details_element',
)
def _hkx_xml_add_mesh_details(parent: ET.Element, mesh_details: object) -> None:
    if not isinstance(mesh_details, Mapping):
        return
    mesh_element = _hkx_xml_mesh_details_element(parent, mesh_details)
    _hkx_xml_add_mesh_detail_summary(mesh_element, mesh_details)
    for source_key, group_tag, row_tag in (('mesh_shape_records', 'mesh_shape_records', 'mesh_shape_record'), ('geometry_sections', 'geometry_sections', 'geometry_section'), ('primitive_buffers', 'primitive_buffers', 'primitive_buffer'), ('aabb_tree_nodes', 'aabb_tree_nodes', 'aabb_tree_record'), ('shape_tag_table', 'shape_tag_table', 'shape_tag_record'), ('mesh_byte_buffers', 'mesh_byte_buffers', 'mesh_byte_buffer')):
        _hkx_xml_add_mesh_record_group(mesh_element, mesh_details, source_key, group_tag, row_tag)
