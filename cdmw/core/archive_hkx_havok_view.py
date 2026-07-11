from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'HkxTagfileSummary',
    'List',
    'Mapping',
    'MutableMapping',
    'Optional',
    'Sequence',
    '_hkx_havok_specialized_group_0',
    '_hkx_havok_specialized_group_1',
    '_hkx_havok_xml_apply_record_reference_to_field',
    '_hkx_havok_xml_make_param_field',
    '_hkx_havok_xml_param_text',
    '_hkx_havok_xml_shape_hint_for_object',
)
def _hkx_havok_xml_specialized_fields(
    object_info: Mapping[str, object],
    fields: Sequence[Mapping[str, object]],
    summary: HkxTagfileSummary,
) -> List[Dict[str, object]]:
    type_name = str(object_info.get("type_name") or "")
    hint = _hkx_havok_xml_shape_hint_for_object(object_info, summary)
    record_by_index = {record.index: record for record in summary.item_records}
    specialized_fields = [dict(field) for field in fields]
    by_param_name: Dict[str, MutableMapping[str, object]] = {}
    for field in specialized_fields:
        hkparam_name = str(field.get("hkparam_name") or field.get("name") or "")
        if hkparam_name and hkparam_name not in by_param_name:
            by_param_name[hkparam_name] = field
    def link_existing(
        param_name: str,
        record_index: Optional[int],
        *,
        reference_kind: str = "decoded_shape_array",
        reference_category: str = "array_data_reference",
        confidence: str = "strong inference",
    ) -> None:
        field = by_param_name.get(param_name)
        if field is None:
            return
        _hkx_havok_xml_apply_record_reference_to_field(
            field,
            record_index=record_index,
            record_by_index=record_by_index,
            reference_kind=reference_kind,
            reference_category=reference_category,
            confidence=confidence,
            description=(
                f"Specialized {type_name} exporter linked this Havok-style parameter to the recovered target ITEM record. "
                "Array count changes remain blocked by CDMW import."
            ),
        )
    def add_if_missing(field: Dict[str, object]) -> None:
        hkparam_name = str(field.get("hkparam_name") or field.get("name") or "")
        if not hkparam_name or hkparam_name in by_param_name:
            return
        specialized_fields.append(field)
        by_param_name[hkparam_name] = field
    def add_row_list_from_prefix(
        *,
        prefix: str,
        param_name: str,
        data_type: str,
        confidence: str,
        description: str,
    ) -> None:
        rows = [
            field
            for field in specialized_fields
            if isinstance(field, Mapping) and str(field.get("name") or "").startswith(prefix)
        ]
        if not rows:
            return
        rows.sort(key=lambda row: int(row.get("offset")) if isinstance(row.get("offset"), int) else 1_000_000)
        values = [row.get("value") for row in rows]
        existing = by_param_name.get(param_name)
        if existing is not None and str(existing.get("name") or "").startswith(prefix):
            existing["type"] = data_type
            existing["value"] = values
            existing["hkparam_text"] = _hkx_havok_xml_param_text(values)
            existing["numelements"] = len(values)
            existing["array_status"] = "row_list"
            existing["reference_status"] = "none"
            existing["confidence"] = confidence
            existing["description"] = description
            return
        add_if_missing(
            _hkx_havok_xml_make_param_field(
                name=param_name,
                data_type=data_type,
                text=_hkx_havok_xml_param_text(values),
                value=values,
                numelements=len(values),
                array_status="row_list",
                confidence=confidence,
                description=description,
            )
        )
    for specialized_group in (
        _hkx_havok_specialized_group_0,
        _hkx_havok_specialized_group_1,
    ):
        if specialized_group(hint, type_name, link_existing, add_if_missing, add_row_list_from_prefix, specialized_fields, record_by_index, object_info, summary):
            break
    return specialized_fields


@bind_archive_hkx_globals(
    'Dict',
    'HkxTagfileSummary',
    'List',
    'Mapping',
    'Optional',
    'Sequence',
    '_hkx_havok_view_add_object',
    '_hkx_havok_xml_record_strings',
    '_hkx_havok_xml_root_recovery',
    '_hkx_havok_xml_stable_object_order',
    '_hkx_havok_xml_type_classes',
    '_hkx_ptch_reference_documents_by_owner_offset',
)
def _hkx_havok_xml_view_document(
    objects: Sequence[Mapping[str, object]],
    summary: HkxTagfileSummary,
    *,
    tagfile_reference_fixups: Optional[Mapping[str, object]] = None,
    object_limit: int = 512,
    field_limit_per_object: int = 128,
) -> Dict[str, object]:
    """Build a Havok-XML-like read-only view from decoded CDMW object records.

    This is not official Havok XML. It intentionally mirrors the familiar hkobject/field shape so exported
    Crimson Desert HKX files are easier to browse while keeping CDMW import byte-preserving and value-only.
    """
    hkobjects: List[Dict[str, object]] = []
    char_strings_by_record = _hkx_havok_xml_record_strings(objects)
    ptch_references_by_owner_offset = _hkx_ptch_reference_documents_by_owner_offset(tagfile_reference_fixups)
    for object_info in objects[:object_limit]:
        _hkx_havok_view_add_object(
            hkobjects, object_info, summary, char_strings_by_record, ptch_references_by_owner_offset,
            field_limit_per_object,
        )
    root_recovery = _hkx_havok_xml_root_recovery(hkobjects)
    stable_object_order = _hkx_havok_xml_stable_object_order(
        hkobjects,
        str(root_recovery.get("toplevelobject") or ""),
    )
    hkobjects.sort(key=lambda obj: int(obj.get("stable_order_index")) if isinstance(obj.get("stable_order_index"), int) else 1_000_000)
    hkclasses = _hkx_havok_xml_type_classes(summary, objects)
    return {
        "format": "cdmw_havok_xml_view_v1",
        "official_havok_xml": False,
        "sdk_version": summary.sdk_version,
        "description": (
            "Read-only Havok-XML-style object view generated from the CDMW decoder. It is meant for browsing "
            "and comparison with older HKX XML workflows; CDMW import ignores this metadata and patches only "
            "supported fixed-size values from the canonical patch sections."
        ),
        "hkpackfile_view": {
            "status": "read_only_parity_view",
            "classversion": summary.sdk_version or "unknown",
            "contentsversion": f"SDKV{summary.sdk_version}" if summary.sdk_version else "unknown",
            "section_name": "__data__",
            "toplevelobject": str(root_recovery.get("toplevelobject") or ""),
            "root_recovery": root_recovery,
            "description": (
                "Havok XML parity view using hkpackfile/hksection/hkobject/hkparam element names. "
                "It is intentionally nested under CDMW metadata and is not a standalone official Havok XML file yet."
            ),
        },
        "root_recovery": root_recovery,
        "hkclasses": hkclasses,
        "object_count": len(objects),
        "exported_object_count": len(hkobjects),
        "truncated_objects": max(0, len(objects) - len(hkobjects)),
        "stable_object_order": stable_object_order,
        "hkobjects": hkobjects,
    }


@bind_archive_hkx_globals(
    'Counter',
    'Dict',
    'List',
    'Mapping',
    'Optional',
    '_hkx_havok_parity_collect_objects',
    'defaultdict',
)
def _hkx_havok_xml_parity_report_document(
    havok_xml_view: Mapping[str, object],
    converter_report: Mapping[str, object],
    *,
    tagfile_reference_fixups: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    hkobjects = havok_xml_view.get("hkobjects")
    object_rows = hkobjects if isinstance(hkobjects, list) else []
    decoded_field_count = int(converter_report.get("decoded_field_count") or 0)
    state = {'layout_field_count': 0, 'emitted_param_count': 0, 'havok_named_param_count': 0, 'cdmw_raw_metadata_param_count': 0, 'array_params_with_numelements': 0, 'resolved_reference_count': 0, 'unresolved_reference_count': 0, 'ptch_fixup_backed_reference_count': 0, 'object_references_resolved_by_ptch': 0, 'object_references_resolved_by_inference': 0}
    reference_category_counts: Counter[str] = Counter()
    reference_resolution_source_counts: Counter[str] = Counter()
    fixup_backed_fields_by_class: Dict[str, set[str]] = defaultdict(set)
    class_rows: Dict[str, Dict[str, object]] = {}
    _hkx_havok_parity_collect_objects(object_rows, reference_category_counts, reference_resolution_source_counts, fixup_backed_fields_by_class, class_rows, state)
    layout_field_count, emitted_param_count, havok_named_param_count, cdmw_raw_metadata_param_count, array_params_with_numelements, resolved_reference_count, unresolved_reference_count, ptch_fixup_backed_reference_count, object_references_resolved_by_ptch, object_references_resolved_by_inference = (state['layout_field_count'], state['emitted_param_count'], state['havok_named_param_count'], state['cdmw_raw_metadata_param_count'], state['array_params_with_numelements'], state['resolved_reference_count'], state['unresolved_reference_count'], state['ptch_fixup_backed_reference_count'], state['object_references_resolved_by_ptch'], state['object_references_resolved_by_inference'])
    ptch_patch_site_count = 0
    ptch_resolved_patch_site_count = 0
    ptch_null_patch_site_count = 0
    ptch_unresolved_patch_site_count = 0
    ptch_target_status_counts: Dict[str, object] = {}
    if isinstance(tagfile_reference_fixups, Mapping):
        ptch_patch_site_count = int(tagfile_reference_fixups.get("ptch_patch_site_count") or 0)
        ptch_resolved_patch_site_count = int(tagfile_reference_fixups.get("ptch_resolved_patch_site_count") or 0)
        ptch_null_patch_site_count = int(tagfile_reference_fixups.get("ptch_null_patch_site_count") or 0)
        ptch_unresolved_patch_site_count = int(tagfile_reference_fixups.get("ptch_unresolved_patch_site_count") or 0)
        status_counts: Counter[str] = Counter()
        sections = tagfile_reference_fixups.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, Mapping):
                    continue
                ptch_tables = section.get("ptch_tables")
                if not isinstance(ptch_tables, list):
                    continue
                for table in ptch_tables:
                    if not isinstance(table, Mapping):
                        continue
                    patch_sites = table.get("patch_sites")
                    if not isinstance(patch_sites, list):
                        continue
                    for site in patch_sites:
                        if isinstance(site, Mapping) and str(site.get("target_status") or ""):
                            status_counts[str(site.get("target_status") or "")] += 1
        ptch_target_status_counts = dict(sorted(status_counts.items()))
    class_parity_rows: List[Dict[str, object]] = []
    for class_row in class_rows.values():
        confidence_counts = class_row.pop("confidence_counts", Counter())
        fixup_fields = class_row.pop("fixup_backed_fields", set())
        class_row["fixup_backed_fields"] = sorted(fixup_fields) if isinstance(fixup_fields, set) else []
        if isinstance(confidence_counts, Counter):
            class_row["confidence_counts"] = dict(sorted(confidence_counts.items()))
            strong_count = int(confidence_counts.get("confirmed") or 0) + int(confidence_counts.get("strong inference") or 0)
        else:
            class_row["confidence_counts"] = {}
            strong_count = 0
        emitted_for_class = int(class_row.get("emitted_param_count") or 0)
        raw_for_class = int(class_row.get("raw_metadata_param_count") or 0)
        class_row["parity_confidence"] = (
            "strong"
            if emitted_for_class > 0 and raw_for_class == 0 and strong_count >= max(1, emitted_for_class // 2)
            else "partial"
            if emitted_for_class > 0
            else "raw"
        )
        class_parity_rows.append(class_row)
    class_parity_rows.sort(key=lambda row: (-int(row.get("emitted_param_count") or 0), str(row.get("class") or "")))
    return {
        "format": "cdmw_hkx_xml_parity_report_v1",
        "status": "read_only_report",
        "imported": False,
        "description": (
            "HKX XML parity report for the read-only Havok-style view. It measures browser/export fidelity only; "
            "CDMW import still ignores Havok XML view data."
        ),
        "exact_fields_decoded": decoded_field_count,
        "layout_fields_available": layout_field_count,
        "havok_like_params_emitted": emitted_param_count,
        "havok_named_params_emitted": havok_named_param_count,
        "unknown_fields_preserved_as_cdmw_raw_metadata": cdmw_raw_metadata_param_count,
        "array_params_with_numelements": array_params_with_numelements,
        "raw_preserved_byte_count": int(converter_report.get("raw_preserved_byte_count") or 0),
        "references_resolved": resolved_reference_count,
        "references_unresolved": unresolved_reference_count,
        "ptch_patch_sites_found": ptch_patch_site_count,
        "ptch_patch_sites_resolved": ptch_resolved_patch_site_count + ptch_null_patch_site_count,
        "ptch_patch_sites_object_resolved": ptch_resolved_patch_site_count,
        "ptch_patch_sites_null": ptch_null_patch_site_count,
        "ptch_patch_sites_unresolved": ptch_unresolved_patch_site_count,
        "ptch_fixup_backed_references": ptch_fixup_backed_reference_count,
        "object_references_resolved_by_ptch": object_references_resolved_by_ptch,
        "object_references_resolved_by_inference": object_references_resolved_by_inference,
        "reference_category_counts": dict(sorted(reference_category_counts.items())),
        "reference_resolution_source_counts": dict(sorted(reference_resolution_source_counts.items())),
        "ptch_target_status_counts": ptch_target_status_counts,
        "fixup_backed_fields_by_class": {
            class_name: sorted(fields)
            for class_name, fields in sorted(fixup_backed_fields_by_class.items())
        },
        "root_object": havok_xml_view.get("root_recovery") if isinstance(havok_xml_view.get("root_recovery"), Mapping) else {},
        "class_parity": class_parity_rows,
        "import_safety": {
            "havok_xml_view_importable": False,
            "safe_modding_path": "CDMW JSON/XML patch document",
            "blocked_until": [
                "field names are stable",
                "references are stable",
                "arrays can be rebuilt safely",
                "representative no-edit export/import is byte-identical",
            ],
        },
    }
