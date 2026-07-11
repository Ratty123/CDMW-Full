from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    'Optional',
    'Sequence',
    '_hkx_xml_add_companion_descriptor_hints',
    '_hkx_xml_add_converter_report',
    '_hkx_xml_add_havok_view',
    '_hkx_xml_add_hkclass_metadata_readiness',
    '_hkx_xml_add_modding_readiness',
    '_hkx_xml_add_modding_workspace',
    '_hkx_xml_add_shapes',
    '_hkx_xml_add_tagfile_reference_fixups',
    '_hkx_xml_add_text',
    '_hkx_xml_clean_text',
    '_hkx_xml_export_content',
    '_hkx_xml_export_physics',
    '_hkx_xml_export_reports',
    '_hkx_xml_export_semantics',
    'build_hkx_editable_geometry_document',
)
def build_hkx_editable_geometry_xml(
    data: bytes,
    virtual_path: str = "",
    companion_descriptor_hints: Optional[Sequence[Mapping[str, object]]] = None,
) -> str:
    """Build a conservative XML patch document for decoded HKX geometry.

    This is a CDMW patch/interchange format, not official Havok XML. It mirrors the JSON document and only
    supports fixed-size numeric edits on import.
    """
    document = build_hkx_editable_geometry_document(data, virtual_path, companion_descriptor_hints)
    root = ET.Element(
        "cdmwHkxGeometryPatch",
        {
            "format": str(document.get("format") or ""),
            "kind": "editable_geometry",
            "official_havok_xml": "false",
        },
    )
    _hkx_xml_add_text(root, "description", document.get("description", ""))
    _hkx_xml_export_reports._hkx_xml_add_source(root, document)
    _hkx_xml_export_reports._hkx_xml_add_compatibility(root, document)
    _hkx_xml_add_modding_readiness(root, document.get("hkx_modding_readiness"))
    _hkx_xml_add_modding_workspace(root, document.get("modding_workspace_v1"))
    _hkx_xml_export_reports._hkx_xml_add_user_guide(root, document)
    _hkx_xml_add_converter_report(root, document)
    _hkx_xml_export_reports._hkx_xml_add_decode_gap_summary(root, document)
    _hkx_xml_export_reports._hkx_xml_add_decoder_evidence_v2(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_real_hkclass_metadata_v2(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_fixup_semantics_v2(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_semantic_model_v1(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_semantic_writer_gate_v1(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_edit_candidate_map_v1(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_hkx_edit_gate_v1(root, document)
    _hkx_xml_export_semantics._hkx_xml_add_class_decoder_evidence_v2(root, document)
    _hkx_xml_export_reports._hkx_xml_add_tag_sections(root, document)
    _hkx_xml_add_tagfile_reference_fixups(root, document)
    _hkx_xml_export_reports._hkx_xml_add_fixup_semantics_report(root, document)
    _hkx_xml_export_reports._hkx_xml_add_type_registry(root, document)
    _hkx_xml_add_havok_view(root, document)
    _hkx_xml_export_reports._hkx_xml_add_parity_report(root, document)
    _hkx_xml_add_hkclass_metadata_readiness(root, document.get("hkclass_metadata_readiness"))
    _hkx_xml_export_content._hkx_xml_add_objects(root, document)
    _hkx_xml_export_content._hkx_xml_add_editor_model(root, document)
    _hkx_xml_export_content._hkx_xml_add_relationship_graph(root, document)
    _hkx_xml_export_content._hkx_xml_add_descriptions(root, document)
    _hkx_xml_export_content._hkx_xml_add_value_layouts(root, document)
    _hkx_xml_export_content._hkx_xml_add_limitations(root, document)
    _hkx_xml_export_content._hkx_xml_add_reimport_policy(root, document)
    _hkx_xml_export_content._hkx_xml_add_schema_observations(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_system(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_names(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_body_summary(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_constraint_summary(root, document)
    _hkx_xml_export_physics._hkx_xml_add_editable_field_catalog(root, document)
    _hkx_xml_export_physics._hkx_xml_add_byte_patch_map(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_tuning(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_body_context(root, document)
    _hkx_xml_export_physics._hkx_xml_add_physics_material_context(root, document)
    descriptor_hints = document.get("companion_descriptor_hints")
    _hkx_xml_add_companion_descriptor_hints(root, document)
    _hkx_xml_export_physics._hkx_xml_add_advanced_payloads(root, document)
    _hkx_xml_export_physics._hkx_xml_add_raw_records(root, document)
    _hkx_xml_add_shapes(root, document)
    ET.indent(root, space="  ")
    return _hkx_xml_clean_text(ET.tostring(root, encoding="unicode"))
