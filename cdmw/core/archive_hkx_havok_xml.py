from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Mapping, Optional, Sequence


def _hkx_havok_xml_context(hkx, data: bytes, virtual_path: str, companion_descriptor_hints):
    document = hkx.build_hkx_editable_geometry_document(data, virtual_path, companion_descriptor_hints)
    havok_xml_view = document.get("havok_xml_view")
    hkpackfile_view = havok_xml_view.get("hkpackfile_view") if isinstance(havok_xml_view, Mapping) else None
    hkobjects = havok_xml_view.get("hkobjects") if isinstance(havok_xml_view, Mapping) else None
    modding_readiness = document.get("hkx_modding_readiness")
    hkclass_metadata_readiness = document.get("hkclass_metadata_readiness")
    native_model_graph = (
        hkclass_metadata_readiness.get("native_model_graph")
        if isinstance(hkclass_metadata_readiness, Mapping)
        else None
    )
    no_edit_binary_writer = (
        hkclass_metadata_readiness.get("no_edit_binary_writer")
        if isinstance(hkclass_metadata_readiness, Mapping)
        else None
    )
    biggest_remaining_gate = (
        hkclass_metadata_readiness.get("biggest_remaining_gate")
        if isinstance(hkclass_metadata_readiness, Mapping)
        else None
    )
    class_internals = (
        hkclass_metadata_readiness.get("class_internals")
        if isinstance(hkclass_metadata_readiness, Mapping)
        else None
    )
    hard_decoder_targets = (
        hkclass_metadata_readiness.get("hard_decoder_targets")
        if isinstance(hkclass_metadata_readiness, Mapping)
        else None
    )
    gui_readiness = (
        hkclass_metadata_readiness.get("gui_readiness")
        if isinstance(hkclass_metadata_readiness, Mapping)
        else None
    )
    semantic_model_v1 = document.get("semantic_model_v1")
    semantic_writer_gate_v1 = document.get("semantic_writer_gate_v1")
    edit_candidate_map_v1 = document.get("edit_candidate_map_v1")
    hkx_edit_gate_v1 = document.get("hkx_edit_gate_v1")
    fixup_semantics_v2 = document.get("fixup_semantics_v2")
    real_hkclass_metadata_v2 = document.get("real_hkclass_metadata_v2")
    class_decoder_evidence_v2 = document.get("class_decoder_evidence_v2")
    if not isinstance(hkpackfile_view, Mapping) or not isinstance(hkobjects, list):
        raise ValueError("HKX document did not produce a Havok XML parity view.")
    return locals()


def _hkx_havok_xml_root(hkx, virtual_path: str, context: Mapping[str, object]) -> ET.Element:
    hkpackfile_view = context["hkpackfile_view"]
    hkclass_metadata_readiness = context["hkclass_metadata_readiness"]
    native_model_graph = context["native_model_graph"]
    no_edit_binary_writer = context["no_edit_binary_writer"]
    biggest_remaining_gate = context["biggest_remaining_gate"]
    class_internals = context["class_internals"]
    hard_decoder_targets = context["hard_decoder_targets"]
    gui_readiness = context["gui_readiness"]
    semantic_model_v1 = context["semantic_model_v1"]
    semantic_writer_gate_v1 = context["semantic_writer_gate_v1"]
    edit_candidate_map_v1 = context["edit_candidate_map_v1"]
    hkx_edit_gate_v1 = context["hkx_edit_gate_v1"]
    fixup_semantics_v2 = context["fixup_semantics_v2"]
    real_hkclass_metadata_v2 = context["real_hkclass_metadata_v2"]
    class_decoder_evidence_v2 = context["class_decoder_evidence_v2"]
    havok_xml_view = context["havok_xml_view"]
    modding_readiness = context["modding_readiness"]
    return ET.Element(
        "hkpackfile",
        {
            "classversion": str(hkpackfile_view.get("classversion") or ""),
            "contentsversion": str(hkpackfile_view.get("contentsversion") or ""),
            "toplevelobject": str(hkpackfile_view.get("toplevelobject") or ""),
            "cdmw_root_method": str(hkpackfile_view.get("root_recovery", {}).get("method") or "")
            if isinstance(hkpackfile_view.get("root_recovery"), Mapping)
            else "",
            "cdmw_named_variant_count": hkx._hkx_xml_scalar(hkpackfile_view.get("root_recovery", {}).get("named_variant_count"))
            if isinstance(hkpackfile_view.get("root_recovery"), Mapping)
            else "",
            "cdmw_format": str(havok_xml_view.get("format") or "cdmw_havok_xml_view_v1"),
            "official_havok_xml": "false",
            "source": virtual_path,
            "cdmw_types_section_status": str(hkclass_metadata_readiness.get("types_section_status") or "")
            if isinstance(hkclass_metadata_readiness, Mapping)
            else "",
            "cdmw_real_hkclass_metadata_recovered": "true"
            if isinstance(hkclass_metadata_readiness, Mapping)
            and bool(hkclass_metadata_readiness.get("real_hkclass_metadata_recovered"))
            else "false",
            "cdmw_native_model_graph_status": str(native_model_graph.get("status") or "")
            if isinstance(native_model_graph, Mapping)
            else "",
            "cdmw_real_hkclass_metadata_v2_status": str(real_hkclass_metadata_v2.get("status") or "")
            if isinstance(real_hkclass_metadata_v2, Mapping)
            else "",
            "cdmw_fixup_semantics_v2_status": str(fixup_semantics_v2.get("status") or "")
            if isinstance(fixup_semantics_v2, Mapping)
            else "",
            "cdmw_semantic_model_v1_status": str(semantic_model_v1.get("status") or "")
            if isinstance(semantic_model_v1, Mapping)
            else "",
            "cdmw_semantic_model_v1_object_count": hkx._hkx_xml_scalar(semantic_model_v1.get("object_count"))
            if isinstance(semantic_model_v1, Mapping)
            else "0",
            "cdmw_semantic_writer_gate_v1_status": str(semantic_writer_gate_v1.get("status") or "")
            if isinstance(semantic_writer_gate_v1, Mapping)
            else "",
            "cdmw_edit_candidate_map_v1_count": hkx._hkx_xml_scalar(edit_candidate_map_v1.get("candidate_count"))
            if isinstance(edit_candidate_map_v1, Mapping)
            else "0",
            "cdmw_hkx_edit_gate_v1_status": str(hkx_edit_gate_v1.get("status") or "")
            if isinstance(hkx_edit_gate_v1, Mapping)
            else "",
            "cdmw_hkx_edit_gate_v1_write_enabled_count": hkx._hkx_xml_scalar(
                hkx_edit_gate_v1.get("write_enabled_candidate_count")
            )
            if isinstance(hkx_edit_gate_v1, Mapping)
            else "0",
            "cdmw_class_decoder_evidence_v2_status": str(class_decoder_evidence_v2.get("status") or "")
            if isinstance(class_decoder_evidence_v2, Mapping)
            else "",
            "cdmw_rust_low_level_parse_status": str(native_model_graph.get("rust_low_level_parse_status") or "")
            if isinstance(native_model_graph, Mapping)
            else "",
            "cdmw_python_builds_richer_graph_export": hkx._hkx_xml_scalar(
                native_model_graph.get("python_builds_richer_graph_export")
            )
            if isinstance(native_model_graph, Mapping)
            else "true",
            "cdmw_no_edit_binary_writer_status": str(no_edit_binary_writer.get("status") or "")
            if isinstance(no_edit_binary_writer, Mapping)
            else "",
            "cdmw_no_edit_roundtrip_mode": str(no_edit_binary_writer.get("no_edit_roundtrip_mode") or "")
            if isinstance(no_edit_binary_writer, Mapping)
            else "",
            "cdmw_biggest_remaining_gate": str(biggest_remaining_gate.get("key") or "")
            if isinstance(biggest_remaining_gate, Mapping)
            else "",
            "cdmw_biggest_remaining_gate_status": str(biggest_remaining_gate.get("status") or "")
            if isinstance(biggest_remaining_gate, Mapping)
            else "",
            "cdmw_class_internals_status": str(class_internals.get("status") or "")
            if isinstance(class_internals, Mapping)
            else "",
            "cdmw_hard_decoder_targets_status": str(hard_decoder_targets.get("status") or "")
            if isinstance(hard_decoder_targets, Mapping)
            else "",
            "cdmw_gui_readiness_status": str(gui_readiness.get("status") or "")
            if isinstance(gui_readiness, Mapping)
            else "",
            "cdmw_modding_readiness": str(modding_readiness.get("per_file_label") or "")
            if isinstance(modding_readiness, Mapping)
            else "",
            "cdmw_fixed_size_patch_importable": hkx._hkx_xml_scalar(modding_readiness.get("fixed_size_patch_importable"))
            if isinstance(modding_readiness, Mapping)
            else "false",
            "cdmw_havok_xml_importable": hkx._hkx_xml_scalar(modding_readiness.get("havok_xml_importable"))
            if isinstance(modding_readiness, Mapping)
            else "false",
        },
    )


def _hkx_havok_xml_add_types(hkx, root: ET.Element, context: Mapping[str, object]) -> None:
    havok_xml_view = context["havok_xml_view"]
    hkclasses = havok_xml_view.get("hkclasses") if isinstance(havok_xml_view, Mapping) else None
    if isinstance(hkclasses, list) and hkclasses:
        types_section = ET.SubElement(root, "hksection", {"name": "__types__"})
        for hkclass in hkclasses:
            if not isinstance(hkclass, Mapping):
                continue
            class_element = ET.SubElement(
                types_section,
                "hkobject",
                {
                    "name": str(hkclass.get("id") or ""),
                    "class": "hkClass",
                    "cdmw_type_index": hkx._hkx_xml_scalar(hkclass.get("index")),
                    "cdmw_object_size": hkx._hkx_xml_scalar(hkclass.get("object_size")),
                    "cdmw_signature": str(hkclass.get("signature") or ""),
                    "cdmw_member_count": hkx._hkx_xml_scalar(hkclass.get("member_count")),
                    "cdmw_metadata_status": str(hkclass.get("metadata_status") or ""),
                    "cdmw_real_hkclass_metadata_recovered": "true"
                    if bool(hkclass.get("real_hkclass_metadata_recovered"))
                    else "false",
                    "cdmw_metadata_source": str(hkclass.get("metadata_source") or ""),
                    "cdmw_member_offset_confidence": str(hkclass.get("member_offset_confidence") or ""),
                },
            )
            ET.SubElement(class_element, "hkparam", {"name": "name"}).text = str(hkclass.get("name") or "")
            ET.SubElement(class_element, "hkparam", {"name": "objectSize"}).text = hkx._hkx_xml_scalar(hkclass.get("object_size"))
            ET.SubElement(class_element, "hkparam", {"name": "version"}).text = hkx._hkx_xml_scalar(hkclass.get("version"))
            ET.SubElement(class_element, "hkparam", {"name": "signature"}).text = str(hkclass.get("signature") or "")
            ET.SubElement(class_element, "hkparam", {"name": "flags"}).text = str(hkclass.get("flags") or "FLAGS_NONE")
            base_name = str(hkclass.get("base_name") or "")
            if base_name and base_name != str(hkclass.get("name") or ""):
                ET.SubElement(class_element, "hkparam", {"name": "cdmwBaseName"}).text = base_name
            unresolved_metadata = hkclass.get("unresolved_real_metadata")
            if isinstance(unresolved_metadata, list) and unresolved_metadata:
                unresolved_param = ET.SubElement(
                    class_element,
                    "hkparam",
                    {"name": "cdmwUnresolvedRealMetadata", "numelements": hkx._hkx_xml_scalar(len(unresolved_metadata))},
                )
                unresolved_param.text = " ".join(str(value) for value in unresolved_metadata)
            template_parameters = hkclass.get("template_parameters")
            if isinstance(template_parameters, list) and template_parameters:
                template_param = ET.SubElement(class_element, "hkparam", {"name": "templateParameters"})
                template_param.text = " ".join(
                    f"{param.get('name')}={param.get('value')}"
                    for param in template_parameters
                    if isinstance(param, Mapping)
                )
            members = hkclass.get("members")
            if isinstance(members, list) and members:
                members_param = ET.SubElement(
                    class_element,
                    "hkparam",
                    {
                        "name": "members",
                        "numelements": hkx._hkx_xml_scalar(len(members)),
                        "cdmw_status": "real_hkClassMember_records"
                        if bool(hkclass.get("real_hkclass_metadata_recovered"))
                        else "synthetic_recovered_members",
                    },
                )
                for member in members:
                    if not isinstance(member, Mapping):
                        continue
                    source_names = member.get("source_names")
                    if isinstance(source_names, (list, tuple)):
                        source_text = " ".join(str(name) for name in source_names)
                    else:
                        source_text = ""
                    ET.SubElement(
                        members_param,
                        "member",
                        {
                            "name": str(member.get("name") or ""),
                            "type": str(member.get("type") or ""),
                            "offset": hkx._hkx_xml_scalar(member.get("offset")),
                            "array_status": str(member.get("array_status") or "none"),
                            "reference_status": str(member.get("reference_status") or "none"),
                            "member_type": str(member.get("member_type") or ""),
                            "member_type_code": hkx._hkx_xml_scalar(member.get("member_type_code")),
                            "subtype": str(member.get("subtype") or ""),
                            "subtype_code": hkx._hkx_xml_scalar(member.get("subtype_code")),
                            "class_ref": str(member.get("class_ref") or ""),
                            "class_ref_record_index": hkx._hkx_xml_scalar(member.get("class_ref_record_index")),
                            "enum_ref": str(member.get("enum_ref") or ""),
                            "enum_ref_record_index": hkx._hkx_xml_scalar(member.get("enum_ref_record_index")),
                            "flags": str(member.get("flags") or "FLAGS_NONE"),
                            "member_flags": hkx._hkx_xml_scalar(member.get("member_flags")),
                            "c_array_size": hkx._hkx_xml_scalar(member.get("c_array_size")),
                            "template_ref": str(member.get("template_ref") or ""),
                            "storage": str(member.get("storage") or ""),
                            "is_array": "true" if bool(member.get("is_array")) else "false",
                            "is_pointer": "true" if bool(member.get("is_pointer")) else "false",
                            "confidence": str(member.get("confidence") or "experimental"),
                            "cdmw_recovered": "true" if bool(member.get("cdmw_recovered")) else "false",
                            "real_hkclass_metadata_recovered": "true"
                            if bool(member.get("real_hkclass_metadata_recovered"))
                            else "false",
                            "cdmw_source_names": source_text,
                        },
                    )


def _hkx_havok_xml_add_objects(hkx, root: ET.Element, context: Mapping[str, object]) -> None:
    hkpackfile_view = context["hkpackfile_view"]
    hkobjects = context["hkobjects"]
    section_element = ET.SubElement(
        root,
        "hksection",
        {
            "name": str(hkpackfile_view.get("section_name") or "__data__"),
        },
    )
    for hkobject in hkobjects:
        if not isinstance(hkobject, Mapping):
            continue
        object_element = ET.SubElement(
            section_element,
            "hkobject",
            {
                "name": str(hkobject.get("id") or ""),
                "class": str(hkobject.get("class") or ""),
                "cdmw_record_index": hkx._hkx_xml_scalar(hkobject.get("record_index")),
                "cdmw_type_index": hkx._hkx_xml_scalar(hkobject.get("type_index")),
                "cdmw_status": str(hkobject.get("status") or ""),
                "cdmw_confidence": str(hkobject.get("confidence") or ""),
                "cdmw_stable_order_index": hkx._hkx_xml_scalar(hkobject.get("stable_order_index")),
                "cdmw_stable_order_key": str(hkobject.get("stable_order_key") or ""),
            },
        )
        fields = hkobject.get("fields")
        if isinstance(fields, list):
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                param_attrs = {
                    "name": str(field.get("hkparam_name") or field.get("name") or ""),
                    "cdmw_data_type": str(field.get("type") or ""),
                    "cdmw_offset": hkx._hkx_xml_scalar(field.get("offset")),
                    "cdmw_confidence": str(field.get("confidence") or ""),
                    "cdmw_editable": "true" if bool(field.get("editable")) else "false",
                    "cdmw_reference_target": str(field.get("reference_target") or ""),
                    "cdmw_reference_kind": str(field.get("reference_kind") or ""),
                    "cdmw_reference_category": str(field.get("reference_category") or ""),
                    "cdmw_reference_status": str(field.get("reference_status") or ""),
                    "cdmw_reference_target_type": str(field.get("reference_target_type") or ""),
                    "cdmw_array_status": str(field.get("array_status") or ""),
                    "cdmw_fixup_backed": "true" if bool(field.get("fixup_backed")) else "false",
                    "cdmw_fixup_source": str(field.get("fixup_source") or ""),
                    "cdmw_reference_resolution_source": str(field.get("reference_resolution_source") or ""),
                    "cdmw_ptch_patch_site_offset": hkx._hkx_xml_scalar(field.get("ptch_patch_site_offset")),
                    "cdmw_ptch_patch_site_hex_offset": str(field.get("ptch_patch_site_hex_offset") or ""),
                    "cdmw_ptch_word_index": hkx._hkx_xml_scalar(field.get("ptch_word_index")),
                    "cdmw_ptch_target_status": str(field.get("ptch_target_status") or ""),
                }
                if field.get("numelements") is not None:
                    param_attrs["numelements"] = hkx._hkx_xml_scalar(field.get("numelements"))
                param = ET.SubElement(object_element, "hkparam", param_attrs)
                param.text = str(field.get("hkparam_text") or "")
                hkx._hkx_xml_add_havok_param_rows(param, field)
        if bool(hkobject.get("raw_preserved")):
            raw_param = ET.SubElement(
                object_element,
                "hkparam",
                {
                    "name": "cdmwRawPayloadPreserved",
                    "cdmw_data_type": "raw-bytes",
                    "cdmw_confidence": "confirmed",
                    "cdmw_editable": "false",
                },
            )
            raw_param.text = "true"


def build_hkx_havok_xml_view_xml(
    data: bytes,
    virtual_path: str = "",
    companion_descriptor_hints: Optional[Sequence[Mapping[str, object]]] = None,
) -> str:
    """Build a standalone read-only hkpackfile-shaped XML view.

    This is closer to the old Havok XML element model than the CDMW patch document, but it is still not
    official Havok XML. It is intended for browsing, diffing, and future schema-parity work.
    """
    from cdmw.core import archive_hkx as hkx

    context = _hkx_havok_xml_context(hkx, data, virtual_path, companion_descriptor_hints)
    root = _hkx_havok_xml_root(hkx, virtual_path, context)
    root.append(
    ET.Comment(
    "Read-only CDMW Havok XML parity view. Use the CDMW patch XML/JSON for safe imports; "
    "this file is not guaranteed to be accepted by official Havok tools."
    )
    )
    _hkx_havok_xml_add_types(hkx, root, context)
    _hkx_havok_xml_add_objects(hkx, root, context)
    ET.indent(root, space="  ")
    return hkx._hkx_xml_clean_text(ET.tostring(root, encoding="unicode"))
