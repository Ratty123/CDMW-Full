from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    '_hkx_hkclass_base_context',
    '_hkx_hkclass_native_context',
    '_hkx_hkclass_readiness_report_0',
    '_hkx_hkclass_readiness_report_1',
    '_hkx_hkclass_readiness_report_2',
    '_hkx_hkclass_status_context',
    '_hkx_hkclass_target_context',
)
def _hkx_hkclass_metadata_readiness_document(
    havok_xml_view: Mapping[str, object],
    native_backend: Mapping[str, object],
    relationship_graph: Mapping[str, object],
) -> Dict[str, object]:
    context = {"native_backend": native_backend}
    _hkx_hkclass_base_context(context, havok_xml_view, native_backend)
    _hkx_hkclass_native_context(context, native_backend)
    _hkx_hkclass_target_context(context, native_backend, relationship_graph)
    _hkx_hkclass_status_context(context)
    report = {}
    report.update(_hkx_hkclass_readiness_report_0(context))
    report.update(_hkx_hkclass_readiness_report_1(context))
    report.update(_hkx_hkclass_readiness_report_2(context))
    return report


@bind_archive_hkx_globals(
    'Dict',
    'HkxTagfileSummary',
    'Mapping',
    '_hkx_native_backend_report_0',
    '_hkx_native_backend_report_1',
    '_hkx_native_backend_report_2',
)
def _hkx_native_backend_document(summary: HkxTagfileSummary) -> Dict[str, object]:
    object_records = list(summary.native_object_records)
    physics_tuning_groups = list(summary.native_physics_tuning_groups)
    tagfile_reference_fixups = dict(summary.native_tagfile_reference_fixups or {})
    fixup_semantics_report = dict(summary.native_fixup_semantics_report or {})
    native_model_graph = dict(summary.native_model_graph or {})
    hard_internal_evidence = dict(summary.native_hard_internal_evidence or {})
    native_real_hkclass_metadata = dict(summary.native_real_hkclass_metadata or {})
    native_real_hkclass_metadata_v2 = dict(summary.native_real_hkclass_metadata_v2 or {})
    native_fixup_semantics_v2 = dict(summary.native_fixup_semantics_v2 or {})
    native_semantic_model_v1 = dict(summary.native_semantic_model_v1 or {})
    native_semantic_writer_gate_v1 = dict(summary.native_semantic_writer_gate_v1 or {})
    native_edit_candidate_map_v1 = dict(summary.native_edit_candidate_map_v1 or {})
    native_hkx_edit_gate_v1 = dict(summary.native_hkx_edit_gate_v1 or {})
    native_class_decoder_evidence_v2 = dict(summary.native_class_decoder_evidence_v2 or {})
    native_decoder_evidence_v2 = dict(summary.native_decoder_evidence_v2 or {})
    native_modding_readiness = dict(summary.native_modding_readiness or {})
    no_edit_binary_writer = dict(summary.native_no_edit_binary_writer or {})
    decoded_object_count = sum(
        1
        for record in object_records
        if isinstance(record, Mapping) and str(record.get("status") or "") in {"editable", "partially_decoded"}
    )
    editable_object_count = sum(
        1
        for record in object_records
        if isinstance(record, Mapping) and str(record.get("status") or "") == "editable"
    )
    tuning_slot_count = 0
    for group in physics_tuning_groups:
        slots = group.get("slots") if isinstance(group, Mapping) else None
        if isinstance(slots, list):
            tuning_slot_count += len(slots)
    fixup_sections = tagfile_reference_fixups.get("sections")
    native_fixup_section_count = len(fixup_sections) if isinstance(fixup_sections, list) else int(tagfile_reference_fixups.get("section_count") or 0)
    context = locals()
    report = {}
    report.update(_hkx_native_backend_report_0(context))
    report.update(_hkx_native_backend_report_1(context))
    report.update(_hkx_native_backend_report_2(context))
    return report


@bind_archive_hkx_globals(
    'Dict',
    'HkxTagfileSummary',
    'List',
    'Mapping',
    '_hkx_modding_readiness_report_0',
    '_hkx_modding_readiness_report_1',
)
def _hkx_modding_readiness_document(
    summary: HkxTagfileSummary,
    converter_report: Mapping[str, object],
    native_backend: Mapping[str, object],
    decoder_evidence_v2: Mapping[str, object],
    hkclass_metadata_readiness: Mapping[str, object],
) -> Dict[str, object]:
    native_readiness = (
        dict(summary.native_modding_readiness or {})
        if isinstance(summary.native_modding_readiness, Mapping)
        else {}
    )
    no_edit_writer = (
        dict(native_backend.get("no_edit_binary_writer") or {})
        if isinstance(native_backend.get("no_edit_binary_writer"), Mapping)
        else {}
    )
    editable_record_count = int(converter_report.get("editable_record_count") or 0)
    decoded_object_count = int(native_backend.get("decoded_object_count") or 0)
    native_patchable_slot_count = int(native_backend.get("modding_readiness_patchable_slot_count") or 0)
    patchable_slot_count = max(editable_record_count, native_patchable_slot_count)
    class_status_count = int(decoder_evidence_v2.get("class_status_count") or 0)
    priority_class_count = int(decoder_evidence_v2.get("priority_class_count") or 0)
    fixed_size_patch_importable = patchable_slot_count > 0
    havok_xml_importable = False
    semantic_rebuild_supported = bool(no_edit_writer.get("semantic_rebuild_supported"))
    byte_identical_no_edit = bool(no_edit_writer.get("byte_identical_no_edit_rebuild_supported"))
    labels: List[str] = []
    native_labels = native_readiness.get("readiness_labels") if isinstance(native_readiness, Mapping) else None
    if isinstance(native_labels, list):
        labels.extend(str(label) for label in native_labels if str(label).strip())
    if fixed_size_patch_importable and "Patchable tuning" not in labels:
        labels.append("Patchable tuning")
    if (decoded_object_count > 0 or class_status_count > 0) and "Read-only decoded" not in labels:
        labels.append("Read-only decoded")
    if (
        priority_class_count > 0
        or not semantic_rebuild_supported
        or bool(hkclass_metadata_readiness.get("biggest_remaining_gate"))
    ) and "Needs semantic rebuild" not in labels:
        labels.append("Needs semantic rebuild")
    if not labels:
        labels.append("Unsupported structure")
    per_file_label = (
        str(native_readiness.get("per_file_label") or "").strip()
        if isinstance(native_readiness, Mapping)
        else ""
    )
    if not per_file_label:
        per_file_label = (
            "Patchable tuning"
            if fixed_size_patch_importable
            else "Read-only decoded"
            if decoded_object_count > 0 or class_status_count > 0
            else "Unsupported structure"
        )
    status = (
        str(native_readiness.get("status") or "").strip()
        if isinstance(native_readiness, Mapping)
        else ""
    )
    if not status:
        status = (
            "fixed_size_patchable"
            if fixed_size_patch_importable
            else "read_only_decoded"
            if decoded_object_count > 0 or class_status_count > 0
            else "unsupported_structure"
        )
    gate = (
        dict(native_readiness.get("semantic_writer_gate") or {})
        if isinstance(native_readiness.get("semantic_writer_gate"), Mapping)
        else {}
    )
    allowed_edits = gate.get("allowed_edits") if isinstance(gate.get("allowed_edits"), list) else []
    blocked_edits = gate.get("blocked_edits") if isinstance(gate.get("blocked_edits"), list) else []
    requirements = gate.get("requirements") if isinstance(gate.get("requirements"), list) else []
    task_groups = [
        dict(group)
        for group in native_readiness.get("task_groups", [])
        if isinstance(group, Mapping)
    ] if isinstance(native_readiness.get("task_groups"), list) else []
    if not task_groups:
        class_rows = [
            row for row in decoder_evidence_v2.get("class_statuses", []) if isinstance(row, Mapping)
        ]

        def _count_class_records(*needles: str) -> int:
            return sum(
                int(row.get("record_count") or 0)
                for row in class_rows
                if any(needle in str(row.get("type_name") or "") for needle in needles)
            )

        task_groups = [
            {
                "key": "collision_size",
                "label": "Collision size",
                "readiness_label": "Read-only decoded",
                "patchable_slot_count": 0,
                "context_record_count": _count_class_records("hknpConvexShape", "hknpMeshShape", "hknpCompoundShape"),
                "risk": "Low when patchable",
                "import_safe": False,
                "evidence": ["decoder_evidence"],
                "description": "Collision shapes and mesh/compound shape context.",
            },
            {
                "key": "body_transform",
                "label": "Body transform",
                "readiness_label": "Patchable tuning" if fixed_size_patch_importable else "Read-only decoded",
                "patchable_slot_count": patchable_slot_count,
                "context_record_count": _count_class_records("ExtendedBodyCinfo"),
                "risk": "High",
                "import_safe": fixed_size_patch_importable,
                "evidence": ["fixed_size_patch_map", "decoder_evidence"],
                "description": "Body construction rows, transform-like values, and mass/inertia-like context.",
            },
            {
                "key": "joint_limits_strength",
                "label": "Joint limits / strength",
                "readiness_label": "Read-only decoded",
                "patchable_slot_count": 0,
                "context_record_count": _count_class_records("Constraint", "Motor"),
                "risk": "Medium to High",
                "import_safe": False,
                "evidence": ["decoder_evidence"],
                "description": "Constraints and motors. Only explicit fixed-size rows are import-safe.",
            },
        ]
    context = locals()
    report = {}
    report.update(_hkx_modding_readiness_report_0(context))
    report.update(_hkx_modding_readiness_report_1(context))
    return report
