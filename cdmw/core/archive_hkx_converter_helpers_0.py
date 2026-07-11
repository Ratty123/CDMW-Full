from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals()
def _hkx_schema_observation_document(summary: HkxTagfileSummary) -> Dict[str, object]:
    records_by_index = {record.index: record for record in summary.item_records}
    payload_summaries: List[Dict[str, object]] = []
    for payload_summary in summary.item_payload_summaries:
        record = records_by_index.get(payload_summary.record_index)
        payload_summaries.append(
            {
                "record_index": payload_summary.record_index,
                "type_index": record.type_index if record is not None else None,
                "type_name": payload_summary.type_name,
                "count": record.count if record is not None else None,
                "data_offset": record.data_offset if record is not None else None,
                "byte_length": payload_summary.byte_length,
                "inferred_stride": payload_summary.inferred_stride,
                "lines": list(payload_summary.lines),
            }
        )
    return {
        "status": "read_only_research",
        "description": (
            "Decoded and inferred tagfile structure. These values are exported for schema recovery and comparison "
            "against multiple HKX files; the importer ignores this section."
        ),
        "type_table": [
            {
                "index": type_info.index,
                "name": type_info.name,
                "display_name": type_info.display_name,
                "template_parameters": [
                    {"name": name, "value": value}
                    for name, value in type_info.template_parameters
                ],
            }
            for type_info in summary.type_infos
        ],
        "record_payload_summaries": payload_summaries,
    }


@bind_archive_hkx_globals(
    '_HKX_ENUM_RECORD_TYPES',
    '_HKX_SCALAR_ARRAY_TYPES',
)
def _hkx_record_role_description(type_name: str) -> str:
    if type_name == "hkFloat3":
        return "Array of three-float vectors. In decoded convex shapes this is usually local-space vertex positions."
    if type_name == "hkVector4":
        return "Array of four-float vectors. In decoded convex shapes this is usually hull plane equations."
    if type_name == "hknpConvexHull::Face":
        return "Convex-hull face table. Each record stores an index-buffer start, vertex count, and metadata byte."
    if type_name == "hkUint8":
        return "Byte array. In decoded convex hulls this is usually the face vertex index buffer."
    if type_name in _HKX_SCALAR_ARRAY_TYPES:
        return _HKX_SCALAR_ARRAY_TYPES[type_name][4]
    if type_name in _HKX_ENUM_RECORD_TYPES:
        return _HKX_ENUM_RECORD_TYPES[type_name] + " Exported read-only until the owning object schema is confirmed."
    if type_name == "hknpConvexHull::Edge":
        return "Convex-hull edge/support table. The exact 2024.2 field meaning is still unverified."
    if type_name == "hknpConvexShape":
        return "Fixed-size convex shape object. It references hull data arrays and contains unverified shape settings."
    if type_name == "hknpShapeMassProperties":
        return "Shape mass-property payload. Exported as four unverified float4 rows for fixed-size edits."
    if type_name == "hkCompressedMassProperties":
        return "Compressed mass-property payload. Exported as read-only packed words and finite-float candidates until the exact Havok 2024.2 schema is recovered."
    if type_name == "hkPackedVector3":
        return "Packed vector array. Exported as read-only quantized byte/word rows; edit support requires recovering the packing scale and owning field."
    if type_name == "hknpShapeProperties::Entry":
        return "Shape property entry. Likely stores material/filter/property metadata; exact fields are not recovered yet."
    if type_name == "hknpCompoundShape":
        return "Compound shape object. It groups child shape instances and tree/free-list data."
    if type_name == "hknpShapeInstance":
        return "Child shape instance payload. It likely links a child shape with transform/filter metadata."
    if type_name == "hknpRagdollData":
        return "Ragdoll container data. It groups physics bodies, constraints, skeleton mapping, and runtime ragdoll metadata."
    if type_name == "hkRootLevelContainer":
        return "Root Havok object container. It usually points to named variants that identify the primary scene/system object."
    if type_name == "hkRootLevelContainer::NamedVariant":
        return "Root named variant entry. It likely links a name, class name, and root object reference."
    if type_name == "hkRefVariant":
        return "Variant reference wrapper. Usually stores a reference to an arbitrary Havok object plus type/context metadata."
    if type_name == "hkStringPtr":
        return "Havok string pointer/reference. Usually references a char record or string data."
    if type_name == "hkMemoryResourceContainer":
        return "Memory/resource container. Exported read-only as reference/count pairs; structural resource edits are not supported."
    if type_name == "hknpPhysicsSceneData":
        return "Physics scene data container. It likely groups one or more hknp physics systems and scene-level metadata."
    if type_name == "hknpPhysicsSystemData":
        return "Physics system container. It likely groups materials, motion properties, bodies, constraints, and shape references."
    if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        return "Physics body construction info. Likely stores body transform, motion/material references, mass-like values, and flags."
    if type_name == "hknpConstraintCinfo":
        return "Constraint construction info. Likely links two bodies with one constraint-data record."
    if type_name == "hknpConstraintData":
        return "Base/variant constraint data record. Concrete constraint layouts may be referenced from nearby records."
    if type_name == "hknpRagdollConstraintData":
        return "Ragdoll joint constraint data. Likely contains joint frames, angular limits, tau/damping-like values, and motors."
    if type_name == "hknpLimitedHingeConstraintData":
        return "Limited hinge joint data. Likely contains hinge frames, angular limits, and motor/damping-like values."
    if type_name == "hknpWheelConstraintData":
        return "Wheel constraint data. Corpus samples show vehicle/wagon files use this heavily; exported read-only as joint-frame and tuning float candidates."
    if type_name == "hknpFixedConstraintData":
        return "Fixed constraint data. Likely stores locked body frames and strength/tau-like tuning; exported read-only until exact fields are confirmed."
    if type_name == "hknpBreakableConstraintData":
        return "Breakable constraint data. Likely stores constraint frames plus break threshold/strength metadata; exported read-only until safe edit rules are known."
    if type_name == "hknpPositionConstraintMotor":
        return "Constraint motor data. Float slots include very likely min/max force and strength/damping-like values."
    if type_name == "hknpSharedMotionProperties":
        return "Shared body motion settings. Likely contains damping, gravity/factor, solver, velocity, and motion tuning values."
    if type_name == "hknpRefDragProperties":
        return "Reference drag-properties payload. Likely stores damping/drag-related tuning for body motion."
    if type_name == "hknpRefMassDistribution":
        return "Reference mass-distribution payload. Likely stores mass/inertia distribution tuning for body motion."
    if type_name == "hknpCylinderShape":
        return "Cylinder collision shape. Corpus vehicle samples use these for wheel/axle-like collision; exported read-only as radius/axis candidates."
    if type_name in {"hknpAabb8TreeNode", "hknpMeshShape::GeometrySection", "hknpMeshShape::GeometrySection::Primitive", "hknpMeshShape::ShapeTagTableEntry"}:
        return "Mesh-shape acceleration/table payload. Rows are separated for schema recovery; topology and AABB rebuilds are not supported yet."
    if type_name == "hkcdSimdTreeNamespace::Node":
        return "Spatial tree node payload used by compound/mesh acceleration structures."
    if type_name == "hkMatrix4":
        return "Read-only 4x4 matrix rows. Commonly used by hkx scene/mesh metadata; editing is disabled until owner semantics are recovered."
    if type_name.startswith("hkx"):
        return "Havok scene/mesh/animation metadata payload. Exported read-only as structured samples for browsing and schema recovery."
    if type_name.startswith("hkArray"):
        return "Havok array-like header. Values may include data references, size, capacity, and flags."
    if type_name.startswith("hkRefPtr"):
        return "Havok reference pointer-like payload. Values may point to another object record."
    if type_name.startswith("hknp"):
        return "Modern Havok Physics object payload. Field layout is partially recovered only."
    return "Decoded ITEM payload. Type-specific Havok 2024.2 field names are not recovered yet."


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_record_status_from_payload(payload_info: Mapping[str, object]) -> Tuple[str, str]:
    type_name = str(payload_info.get("type_name") or "")
    editable_values = payload_info.get("editable_values")
    interpretation = payload_info.get("interpretation")
    layout = payload_info.get("layout")
    if isinstance(editable_values, Mapping):
        kind = str(editable_values.get("kind") or "")
        if kind in {"float3_rows", "float4_rows", "face_records", "byte_values", "uint16_pairs"}:
            return "editable", "strong inference"
        if kind == "fixed_float_slots":
            return "editable", "experimental"
        return "editable", "experimental"
    if type_name in {
        "hkFloat3",
        "hkVector4",
        "hknpConvexHull::Face",
        "hkUint8",
        "hknpConvexHull::Edge",
    }:
        return "decoded", "strong inference"
    if type_name.startswith("hkArray") or type_name.startswith("hkRefPtr"):
        return "partially_decoded", "experimental"
    if isinstance(interpretation, Mapping):
        decoded_keys = set(interpretation) - {"role", "field_status", "u32_words_sample", "possible_internal_links"}
        if decoded_keys:
            return "partially_decoded", "experimental"
    if isinstance(layout, Mapping):
        fields = layout.get("fields")
        if isinstance(fields, list) and fields:
            if any(isinstance(field, Mapping) and field.get("editable") is True for field in fields):
                return "editable", "experimental"
            if any(isinstance(field, Mapping) and str(field.get("confidence") or "") != "raw" for field in fields):
                return "partially_decoded", "experimental"
    return "raw_preserved", "raw"


@bind_archive_hkx_globals(
    '_hkx_missing_decoder_requirements_for_type',
)
def _hkx_decode_state_from_payload(payload_info: Mapping[str, object], status: str, confidence: str) -> Dict[str, object]:
    type_name = str(payload_info.get("type_name") or "")
    if status == "editable":
        return {
            "status_label": "Patchable value",
            "decode_category": "fixed_size_patchable_value",
            "status_reason": "A fixed-size value location is mapped and can be patched without changing HKX structure.",
            "missing_requirements": [
                "byte-identical native no-edit writer before Havok XML import",
                "real hkClass metadata for official Havok member naming",
            ],
        }
    if status == "decoded":
        return {
            "status_label": "Decoded value rows",
            "decode_category": "decoded_value_table",
            "status_reason": "The payload is decoded into stable row values for browsing/export.",
            "missing_requirements": [
                "owner hkClass metadata for exact official member names",
                "native no-edit writer before import beyond CDMW fixed-size patches",
            ],
        }
    if status == "partially_decoded":
        category, reason, missing = _hkx_missing_decoder_requirements_for_type(type_name)
        return {
            "status_label": "Readable, not fully mapped",
            "decode_category": category,
            "status_reason": reason,
            "missing_requirements": missing,
        }
    category, reason, missing = _hkx_missing_decoder_requirements_for_type(type_name)
    raw_reason = "No stable structured decode is available yet; bytes are preserved for safe roundtrip/export."
    if confidence and str(confidence).lower() != "raw":
        raw_reason = reason
    return {
        "status_label": "Raw preserved",
        "decode_category": category,
        "status_reason": raw_reason,
        "missing_requirements": missing,
    }


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_decode_state_from_payload',
    '_hkx_record_status_from_payload',
)
def _hkx_converter_record_document(payload_info: Mapping[str, object]) -> Dict[str, object]:
    status, confidence = _hkx_record_status_from_payload(payload_info)
    decode_state = _hkx_decode_state_from_payload(payload_info, status, confidence)
    interpretation = payload_info.get("interpretation")
    decoded_fields: Dict[str, object] = {}
    references: List[object] = []
    if isinstance(interpretation, Mapping):
        for key, value in interpretation.items():
            if key in {"role", "field_status", "u32_words_sample", "possible_internal_links", "possible_record_references"}:
                continue
            decoded_fields[str(key)] = value
        link_documents = interpretation.get("possible_record_references")
        if isinstance(link_documents, list):
            references = [dict(link) for link in link_documents if isinstance(link, Mapping)]
        links = interpretation.get("possible_internal_links")
        if isinstance(links, list):
            if references:
                decoded_fields["legacy_reference_summary"] = [str(link) for link in links]
            else:
                references = [str(link) for link in links]
    layout = payload_info.get("layout")
    if isinstance(layout, Mapping):
        layout_fields = layout.get("fields")
        if isinstance(layout_fields, list):
            decoded_fields["layout_field_count"] = len(layout_fields)
        layout_references = layout.get("references")
        if isinstance(layout_references, list):
            seen_reference_keys = {
                (
                    reference.get("offset"),
                    reference.get("target_record_index"),
                    reference.get("reference_kind"),
                )
                for reference in references
                if isinstance(reference, Mapping)
            }
            for reference in layout_references:
                if not isinstance(reference, Mapping):
                    continue
                reference_key = (
                    reference.get("offset"),
                    reference.get("target_record_index"),
                    reference.get("reference_kind"),
                )
                if reference_key in seen_reference_keys:
                    continue
                seen_reference_keys.add(reference_key)
                references.append(dict(reference))
    return {
        "record_index": payload_info.get("record_index"),
        "type_index": payload_info.get("type_index"),
        "type_name": payload_info.get("type_name"),
        "count": payload_info.get("count"),
        "data_offset": payload_info.get("data_offset"),
        "absolute_data_offset": payload_info.get("absolute_data_offset"),
        "byte_length": payload_info.get("byte_length"),
        "status": status,
        "confidence": confidence,
        **decode_state,
        "description": payload_info.get("description", ""),
        "decoded_fields": decoded_fields,
        "references": references,
        "layout": payload_info.get("layout"),
        "raw_ranges": payload_info.get("raw_ranges"),
        "editable_values": payload_info.get("editable_values"),
    }


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_editable_value_count(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    kind = str(value.get("kind") or "")
    if kind in {"float3_rows", "float4_rows"}:
        rows = value.get("rows")
        if isinstance(rows, list):
            return sum(len(row) for row in rows if isinstance(row, list))
    if kind == "face_records":
        records = value.get("records")
        if isinstance(records, list):
            return len(records) * 3
    if kind == "byte_values":
        values = value.get("values")
        return len(values) if isinstance(values, list) else 0
    if kind == "uint16_pairs":
        pairs = value.get("pairs")
        if isinstance(pairs, list):
            return len(pairs) * 2
    if kind == "fixed_float_slots":
        items = value.get("items")
        if not isinstance(items, list):
            return 0
        return sum(
            len(item.get("float_slots", []))
            for item in items
            if isinstance(item, Mapping) and isinstance(item.get("float_slots"), list)
        )
    return 0


@bind_archive_hkx_globals()
def _hkx_compatibility_status_from_counts(
    *,
    sdk_version: str,
    item_record_count: int,
    payload_record_count: int,
    size_matches: bool,
    editable_target_count: int,
    preview_linked_target_count: int,
) -> str:
    if sdk_version != "20240200" or item_record_count <= 0:
        return "unsupported"
    if not size_matches or payload_record_count <= 0:
        return "inspectable"
    if preview_linked_target_count > 0 and editable_target_count > 0:
        return "preview_linked"
    if editable_target_count > 0:
        return "value_editable"
    if payload_record_count >= item_record_count:
        return "roundtrip_safe"
    return "inspectable"


@bind_archive_hkx_globals()
def _hkx_decode_gap_friendly_label(category: str, status: str) -> str:
    category_key = str(category or "").strip()
    if category_key == "mesh_shape_internals":
        return "Readable, missing mesh primitive layout"
    if category_key == "physics_class_members":
        return "Readable, missing real hkClass members"
    if category_key == "shape_internals":
        return "Readable, missing shape internals"
    if category_key == "material_property_entries":
        return "Readable, missing material/property names"
    if category_key == "compressed_mass_properties":
        return "Readable, missing compressed mass rules"
    if category_key == "array_owner_context":
        return "Readable, missing array owner type"
    if category_key == "reference_pointer_context":
        return "Readable, missing reference semantics"
    if category_key == "root_container_semantics":
        return "Readable, missing root container semantics"
    if category_key == "skeleton_animation_containers":
        return "Readable, missing skeleton/animation tables"
    if "raw" in str(status or "").casefold():
        return "Raw preserved, decoder needed"
    return "Readable, not fully mapped"


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_decode_gap_friendly_label',
    '_hkx_missing_decoder_requirements_for_type',
)
def _hkx_decode_gap_summary_document(
    converter_report: Mapping[str, object],
    decoder_evidence_v2: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    coverage_rows = converter_report.get("decode_coverage_by_type")
    if not isinstance(coverage_rows, list):
        coverage_rows = []
    gaps: List[Dict[str, object]] = []
    total_unresolved_bytes = 0
    total_partial_records = 0
    total_raw_records = 0
    for row in coverage_rows:
        if not isinstance(row, Mapping):
            continue
        type_name = str(row.get("type_name") or "")
        if not type_name:
            continue
        status_counts = row.get("status_counts")
        if not isinstance(status_counts, Mapping):
            status_counts = {}
        partial_records = int(status_counts.get("partially_decoded") or 0)
        raw_records = int(status_counts.get("raw_preserved") or status_counts.get("raw") or 0)
        editable_slots = int(row.get("editable_slot_count") or 0)
        raw_bytes = int(row.get("raw_preserved_byte_count") or 0)
        unresolved_bytes = int(row.get("unresolved_layout_byte_count") or 0)
        candidate_bytes = int(row.get("candidate_layout_byte_count") or 0)
        typed_bytes = int(row.get("typed_layout_byte_count") or 0)
        byte_length = int(row.get("byte_length") or 0)
        if raw_records <= 0 and partial_records <= 0:
            continue
        if editable_slots > 0 and unresolved_bytes <= 0 and raw_bytes <= 0:
            continue
        category, status_reason, missing_requirements = _hkx_missing_decoder_requirements_for_type(type_name)
        evidence_row: Optional[Mapping[str, object]] = None
        evidence_class_rows = (
            decoder_evidence_v2.get("class_statuses")
            if isinstance(decoder_evidence_v2, Mapping)
            else None
        )
        if isinstance(evidence_class_rows, list):
            found_evidence_row = next(
                (
                    item
                    for item in evidence_class_rows
                    if isinstance(item, Mapping) and str(item.get("type_name") or "") == type_name
                ),
                None,
            )
            if isinstance(found_evidence_row, Mapping):
                evidence_row = found_evidence_row
                evidence_missing = evidence_row.get("missing_requirements")
                if isinstance(evidence_missing, list) and evidence_missing:
                    missing_requirements = [str(value) for value in evidence_missing if str(value).strip()]
        unresolved_volume = raw_bytes or unresolved_bytes or max(0, byte_length - typed_bytes)
        if unresolved_volume <= 0 and partial_records > 0:
            unresolved_volume = candidate_bytes or byte_length
        gap_status = "raw_preserved" if raw_records and not partial_records else "partially_decoded" if partial_records and not raw_records else "mixed"
        total_unresolved_bytes += max(0, unresolved_volume)
        total_partial_records += partial_records
        total_raw_records += raw_records
        gaps.append(
            {
                "type_name": type_name,
                "record_count": int(row.get("record_count") or 0),
                "partial_record_count": partial_records,
                "raw_preserved_record_count": raw_records,
                "byte_length": byte_length,
                "typed_layout_byte_count": typed_bytes,
                "candidate_layout_byte_count": candidate_bytes,
                "unresolved_byte_count": unresolved_volume,
                "decoded_field_count": int(row.get("decoded_field_count") or 0),
                "editable_slot_count": editable_slots,
                "reference_candidate_count": int(row.get("reference_candidate_count") or 0),
                "decode_category": category,
                "status": gap_status,
                "friendly_status_label": (
                    str(evidence_row.get("friendly_status"))
                    if evidence_row is not None and evidence_row.get("friendly_status")
                    else _hkx_decode_gap_friendly_label(category, gap_status)
                ),
                "what_this_means": status_reason,
                "what_is_missing": "; ".join(str(value) for value in missing_requirements if str(value).strip()),
                "missing_requirements": missing_requirements,
                "suggested_next_decoder_step": missing_requirements[0] if missing_requirements else "recover real hkClass metadata",
                "safe_edit_policy": "read_only" if editable_slots <= 0 else "fixed_size_patch_only",
                "priority_score": unresolved_volume + candidate_bytes + partial_records * 256 + raw_records * 512,
            }
        )
    gaps.sort(
        key=lambda gap: (
            -int(gap.get("priority_score") or 0),
            -int(gap.get("unresolved_byte_count") or 0),
            str(gap.get("type_name") or ""),
        )
    )
    for rank, gap in enumerate(gaps, start=1):
        gap["priority_rank"] = rank
        gap["unresolved_byte_share"] = (
            float(int(gap.get("unresolved_byte_count") or 0) / total_unresolved_bytes)
            if total_unresolved_bytes
            else 0.0
        )
    return {
        "format": "cdmw_hkx_decode_gap_summary_v1",
        "status": "has_decode_gaps" if gaps else "no_ranked_decode_gaps",
        "description": (
            "Ranked read-only evidence for HKX classes that are readable but not fully decoded. "
            "This is used to explain partially decoded rows in the editor; it does not enable new imports."
        ),
        "gap_count": len(gaps),
        "partial_record_count": total_partial_records,
        "raw_preserved_record_count": total_raw_records,
        "total_unresolved_byte_count": total_unresolved_bytes,
        "gaps": gaps[:128],
        "truncated_gap_count": max(0, len(gaps) - 128),
    }
