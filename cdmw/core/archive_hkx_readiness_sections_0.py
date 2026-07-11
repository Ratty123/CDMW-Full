from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Counter',
    'Mapping',
    '_HKX_NATIVE_MODEL_GRAPH_REQUIREMENTS',
    '_HKX_NO_EDIT_BINARY_WRITER_REQUIREMENTS',
    '_HKX_REAL_HKCLASS_METADATA_REQUIREMENTS',
)
def _hkx_hkclass_base_context(context, havok_xml_view, native_backend):
    hkclasses = havok_xml_view.get('hkclasses')
    class_rows = hkclasses if isinstance(hkclasses, list) else []
    class_count = len(class_rows)
    real_class_count = sum((1 for row in class_rows if isinstance(row, Mapping) and bool(row.get('real_hkclass_metadata_recovered'))))
    synthetic_class_count = sum((1 for row in class_rows if isinstance(row, Mapping) and str(row.get('metadata_status') or '') == 'synthetic_recovered_hkClass'))
    recovered_member_count = sum((int(row.get('recovered_member_count') or 0) for row in class_rows if isinstance(row, Mapping)))
    declared_member_count = sum((int(row.get('declared_member_count') or 0) for row in class_rows if isinstance(row, Mapping)))
    unresolved_metadata_counts: Counter[str] = Counter()
    for row in class_rows:
        if not isinstance(row, Mapping):
            continue
        unresolved = row.get('unresolved_real_metadata')
        if isinstance(unresolved, list):
            for key in unresolved:
                unresolved_metadata_counts[str(key)] += 1
    requirements = [{'key': key, 'label': label, 'recovered': False, 'description': description} for key, label, description in _HKX_REAL_HKCLASS_METADATA_REQUIREMENTS]
    native_graph_requirements = [{'key': key, 'label': label, 'available': False, 'status': 'missing', 'description': description} for key, label, description in _HKX_NATIVE_MODEL_GRAPH_REQUIREMENTS]
    binary_writer_requirements = [{'key': key, 'label': label, 'passed': False, 'status': 'missing', 'description': description} for key, label, description in _HKX_NO_EDIT_BINARY_WRITER_REQUIREMENTS]
    native_available = bool(native_backend.get('available'))
    native_object_record_count = int(native_backend.get('object_record_count') or 0)
    native_fixup_section_count = int(native_backend.get('tagfile_reference_fixup_section_count') or 0)
    native_fixup_semantics_available = bool(native_backend.get('fixup_semantics_report'))
    native_real_hkclass_metadata = native_backend.get('real_hkclass_metadata') if isinstance(native_backend.get('real_hkclass_metadata'), Mapping) else {}
    native_real_hkclass_status = str(native_backend.get('real_hkclass_metadata_status') or '')
    native_real_hkclass_class_count = int(native_backend.get('real_hkclass_metadata_class_count') or 0)
    native_real_hkclass_member_count = int(native_backend.get('real_hkclass_metadata_member_count') or 0)
    native_real_hkclass_recovered_requirements = dict(native_backend.get('real_hkclass_metadata_recovered_requirements') or {}) if isinstance(native_backend.get('real_hkclass_metadata_recovered_requirements'), Mapping) else {}
    if not native_real_hkclass_recovered_requirements and isinstance(native_real_hkclass_metadata, Mapping):
        recovered = native_real_hkclass_metadata.get('recovered_requirements')
        if isinstance(recovered, Mapping):
            native_real_hkclass_recovered_requirements = dict(recovered)
    for requirement in requirements:
        key = str(requirement.get('key') or '')
        requirement['recovered'] = bool(native_real_hkclass_recovered_requirements.get(key))
    context.update({'binary_writer_requirements': binary_writer_requirements, 'class_count': class_count, 'class_rows': class_rows, 'declared_member_count': declared_member_count, 'hkclasses': hkclasses, 'native_available': native_available, 'native_fixup_section_count': native_fixup_section_count, 'native_fixup_semantics_available': native_fixup_semantics_available, 'native_graph_requirements': native_graph_requirements, 'native_object_record_count': native_object_record_count, 'native_real_hkclass_class_count': native_real_hkclass_class_count, 'native_real_hkclass_member_count': native_real_hkclass_member_count, 'native_real_hkclass_metadata': native_real_hkclass_metadata, 'native_real_hkclass_recovered_requirements': native_real_hkclass_recovered_requirements, 'native_real_hkclass_status': native_real_hkclass_status, 'real_class_count': real_class_count, 'recovered_member_count': recovered_member_count, 'requirements': requirements, 'synthetic_class_count': synthetic_class_count, 'unresolved_metadata_counts': unresolved_metadata_counts})


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
)
def _hkx_hkclass_native_context(context, native_backend):
    native_graph_doc = native_backend.get('native_model_graph') if isinstance(native_backend.get('native_model_graph'), Mapping) else {}
    native_graph_node_count = int(native_backend.get('native_model_graph_node_count') or 0)
    native_graph_edge_count = int(native_backend.get('native_model_graph_edge_count') or 0)
    native_graph_fixup_edge_count = int(native_backend.get('native_model_graph_fixup_backed_reference_edge_count') or 0)
    native_graph_owner_array_count = int(native_backend.get('native_model_graph_owner_array_count') or 0)
    native_graph_root = native_backend.get('native_model_graph_root') if isinstance(native_backend.get('native_model_graph_root'), Mapping) else {}
    native_graph_status = str(native_backend.get('native_model_graph_status') or '') or (str(native_graph_doc.get('status') or '') if isinstance(native_graph_doc, Mapping) else '')
    native_object_graph_available = native_graph_node_count > 0
    native_fixup_backed_reference_graph_available = native_graph_fixup_edge_count > 0
    native_relationship_graph_available = native_graph_edge_count > 0
    native_owner_array_resolution_available = native_graph_owner_array_count > 0
    native_root_method = str(native_graph_root.get('method') or '')
    native_root_container_semantics_available = native_root_method in {'native_hkRootLevelContainer', 'native_named_variant_target', 'native_preferred_root_class'}
    native_graph_capability_available = {'fixup_backed_object_refs': native_fixup_backed_reference_graph_available, 'owner_arrays': native_owner_array_resolution_available, 'root_container_semantics': native_root_container_semantics_available, 'native_export_graph': native_object_graph_available}
    for requirement in context['native_graph_requirements']:
        key = str(requirement.get('key') or '')
        available = bool(native_graph_capability_available.get(key))
        requirement['available'] = available
        requirement['status'] = 'available_native_partial' if available else 'missing'
    native_no_edit_writer = native_backend.get('no_edit_binary_writer') if isinstance(native_backend.get('no_edit_binary_writer'), Mapping) else {}
    native_no_edit_available = bool(native_backend.get('native_read_model_write_available') or (isinstance(native_no_edit_writer, Mapping) and native_no_edit_writer.get('native_read_model_write_available')))
    native_no_edit_byte_identical = bool(native_backend.get('byte_identical_no_edit_rebuild_supported') or (isinstance(native_no_edit_writer, Mapping) and native_no_edit_writer.get('byte_identical_no_edit_rebuild_supported')))
    native_no_edit_status = str(native_backend.get('no_edit_binary_writer_status') or '') or (str(native_no_edit_writer.get('status') or '') if isinstance(native_no_edit_writer, Mapping) else '') or ('byte_identical' if native_no_edit_byte_identical else 'not_started')
    native_no_edit_roundtrip_mode = str(native_backend.get('no_edit_roundtrip_mode') or '') or (str(native_no_edit_writer.get('no_edit_roundtrip_mode') or '') if isinstance(native_no_edit_writer, Mapping) else '') or ('native_read_model_write_lossless_bytes' if native_no_edit_available else 'not_available')
    native_no_edit_pipeline = str(native_backend.get('read_model_write_pipeline') or '') or (str(native_no_edit_writer.get('read_model_write_pipeline') or '') if isinstance(native_no_edit_writer, Mapping) else '') or ('raw_preserving_model' if native_no_edit_available else 'missing')
    binary_writer_requirement_rows: List[Dict[str, object]] = []
    for requirement in context['binary_writer_requirements']:
        key = str(requirement.get('key') or '')
        passed = native_no_edit_byte_identical and key in {'section_table_roundtrip', 'item_table_roundtrip', 'fixup_table_roundtrip', 'unknown_payload_roundtrip'}
        requirement_row = dict(requirement)
        requirement_row['passed'] = passed
        requirement_row['status'] = 'passed_file_level' if passed else 'missing'
        if key == 'representative_byte_identity' and native_no_edit_byte_identical:
            requirement_row['status'] = 'representative_corpus_pending'
        binary_writer_requirement_rows.append(requirement_row)
    context.update({'binary_writer_requirement_rows': binary_writer_requirement_rows, 'native_fixup_backed_reference_graph_available': native_fixup_backed_reference_graph_available, 'native_graph_capability_available': native_graph_capability_available, 'native_graph_doc': native_graph_doc, 'native_graph_edge_count': native_graph_edge_count, 'native_graph_fixup_edge_count': native_graph_fixup_edge_count, 'native_graph_node_count': native_graph_node_count, 'native_graph_owner_array_count': native_graph_owner_array_count, 'native_graph_root': native_graph_root, 'native_graph_status': native_graph_status, 'native_no_edit_available': native_no_edit_available, 'native_no_edit_byte_identical': native_no_edit_byte_identical, 'native_no_edit_pipeline': native_no_edit_pipeline, 'native_no_edit_roundtrip_mode': native_no_edit_roundtrip_mode, 'native_no_edit_status': native_no_edit_status, 'native_no_edit_writer': native_no_edit_writer, 'native_object_graph_available': native_object_graph_available, 'native_owner_array_resolution_available': native_owner_array_resolution_available, 'native_relationship_graph_available': native_relationship_graph_available, 'native_root_container_semantics_available': native_root_container_semantics_available, 'native_root_method': native_root_method})


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Sequence',
    '_HKX_CLASS_INTERNAL_TARGETS',
    '_HKX_GUI_USABILITY_TARGETS',
    '_HKX_HARD_DECODER_TARGETS',
)
def _hkx_hkclass_target_context(context, native_backend, relationship_graph):
    graph_node_count = int(relationship_graph.get('node_count') or 0) if isinstance(relationship_graph, Mapping) else 0
    graph_edge_count = int(relationship_graph.get('edge_count') or 0) if isinstance(relationship_graph, Mapping) else 0
    class_names = {str(row.get('name') or '') for row in context['class_rows'] if isinstance(row, Mapping)}
    real_class_names = {str(row.get('name') or '') for row in context['class_rows'] if isinstance(row, Mapping) and bool(row.get('real_hkclass_metadata_recovered'))}
    native_hard_internal_evidence = native_backend.get('hard_internal_evidence') if isinstance(native_backend.get('hard_internal_evidence'), Mapping) else {}
    native_hard_targets = native_hard_internal_evidence.get('targets') if isinstance(native_hard_internal_evidence, Mapping) else None
    native_hard_targets_by_key = {str(target.get('key') or ''): target for target in native_hard_targets if isinstance(target, Mapping) and str(target.get('key') or '')} if isinstance(native_hard_targets, list) else {}

    def _has_class_prefix(prefixes: Sequence[str]) -> bool:
        return any((any((name.startswith(prefix) for prefix in prefixes)) for name in class_names))
    class_internal_targets: List[Dict[str, object]] = []
    for class_name, needed_internals in _HKX_CLASS_INTERNAL_TARGETS:
        present = class_name in class_names
        if class_name == 'skeleton_animation_containers':
            present = _has_class_prefix(('hkSkeleton', 'hkaAnimationContainer', 'hkaSkeletonMapper'))
        real_member_metadata = class_name in real_class_names
        class_internal_targets.append({'class': class_name, 'present_in_file': present, 'status': 'real_hkclass_members_recovered_hard_internals_open' if real_member_metadata else 'partial_cdmw_recovery' if present else 'needs_corpus_sample', 'real_internals_recovered': False, 'real_member_metadata_recovered': real_member_metadata, 'source': 'native_real_hkClassMember_metadata_plus_class_specific_python_decoder' if real_member_metadata else 'synthetic_hkclass_rows_plus_class_specific_python_decoder' if present else 'not_observed', 'needed_internals': needed_internals})
    hard_decoder_targets: List[Dict[str, object]] = []
    for key, label, description, class_prefixes in _HKX_HARD_DECODER_TARGETS:
        native_target = native_hard_targets_by_key.get(key, {})
        present = _has_class_prefix(class_prefixes) or bool(native_target.get('present_in_file') if isinstance(native_target, Mapping) else False)
        observed_fields = list(native_target.get('observed_fields') or []) if isinstance(native_target, Mapping) and isinstance(native_target.get('observed_fields'), list) else []
        observed_types = list(native_target.get('observed_types') or []) if isinstance(native_target, Mapping) and isinstance(native_target.get('observed_types'), list) else []
        record_indices = list(native_target.get('record_indices') or []) if isinstance(native_target, Mapping) and isinstance(native_target.get('record_indices'), list) else []
        unresolved_blockers = list(native_target.get('unresolved_blockers') or []) if isinstance(native_target, Mapping) and isinstance(native_target.get('unresolved_blockers'), list) else []
        if not unresolved_blockers:
            unresolved_blockers = ['needs representative corpus proof', 'read-only until semantic rebuild rules are known']
        hard_decoder_targets.append({'key': key, 'label': label, 'present_in_file': present, 'status': (str(native_target.get('status') or '') if isinstance(native_target, Mapping) else '') or ('open_observed_unproven' if present else 'open_needs_corpus_sample'), 'proof_status': (str(native_target.get('proof_status') or '') if isinstance(native_target, Mapping) else '') or ('needs_corpus_proof' if present else 'needs_corpus_sample'), 'resolved': False, 'import_blocking': True, 'class_prefixes': list(class_prefixes), 'observed_record_count': int(native_target.get('observed_record_count') or 0) if isinstance(native_target, Mapping) else 0, 'observed_byte_count': int(native_target.get('observed_byte_count') or 0) if isinstance(native_target, Mapping) else 0, 'observed_types': observed_types, 'observed_fields': observed_fields, 'record_indices': record_indices, 'unresolved_blockers': unresolved_blockers, 'confidence': (str(native_target.get('confidence') or '') if isinstance(native_target, Mapping) else '') or ('experimental' if present else 'none'), 'description': description})
    gui_targets = [{'key': key, 'label': label, 'status': target_status, 'complete': target_status == 'complete', 'description': description} for key, label, target_status, description in _HKX_GUI_USABILITY_TARGETS]
    context.update({'_has_class_prefix': _has_class_prefix, 'class_internal_targets': class_internal_targets, 'class_names': class_names, 'graph_edge_count': graph_edge_count, 'graph_node_count': graph_node_count, 'gui_targets': gui_targets, 'hard_decoder_targets': hard_decoder_targets, 'native_hard_internal_evidence': native_hard_internal_evidence, 'native_hard_targets': native_hard_targets, 'native_hard_targets_by_key': native_hard_targets_by_key, 'real_class_names': real_class_names})


@bind_archive_hkx_globals()
def _hkx_hkclass_status_context(context, ):
    native_model_graph_status = context['native_graph_status'] if context['native_object_graph_available'] else 'partial_native_parse_python_graph' if context['native_available'] and (context['native_object_record_count'] or context['native_fixup_section_count'] or context['native_fixup_semantics_available']) else 'python_only_graph'
    status = 'real_hkclass_metadata_recovered' if context['class_count'] > 0 and context['real_class_count'] == context['class_count'] else 'mixed_real_and_synthetic_hkclass_metadata' if context['real_class_count'] > 0 else 'synthetic_types_native_model_graph_partial' if native_model_graph_status in {'partial_native_parse_python_graph', 'native_model_graph_partial', 'native_object_nodes_only'} else 'synthetic_types_python_model_graph'
    types_section_status = 'real_hkClass_metadata' if context['class_count'] > 0 and context['real_class_count'] == context['class_count'] else 'mixed_real_and_synthetic_hkClass' if context['real_class_count'] > 0 else 'synthetic_recovered_hkClass' if context['synthetic_class_count'] else 'not_recovered'
    context.update({'native_model_graph_status': native_model_graph_status, 'status': status, 'types_section_status': types_section_status})


@bind_archive_hkx_globals()
def _hkx_hkclass_readiness_report_0(context):
    return {
        'format': 'cdmw_hkx_hkclass_metadata_readiness_v1',
        'status': context['status'],
        'description': 'Readiness gate for real Havok hkClass metadata and the native model graph. The current __types__ section is a synthetic browsing aid built from TNA1 names and recovered CDMW layouts, not true Havok class metadata.',
        'types_section_status': context['types_section_status'],
        '__types_section_status': context['types_section_status'],
        'real_hkclass_metadata_recovered': context['class_count'] > 0 and context['real_class_count'] == context['class_count'],
        'real_hkclass_metadata_status': context['native_real_hkclass_status'],
        'native_real_hkclass_metadata_class_count': context['native_real_hkclass_class_count'],
        'native_real_hkclass_metadata_member_count': context['native_real_hkclass_member_count'],
    }


@bind_archive_hkx_globals()
def _hkx_hkclass_readiness_report_1(context):
    return {
        'native_real_hkclass_metadata_recovered_requirements': context['native_real_hkclass_recovered_requirements'],
        'class_count': context['class_count'],
        'synthetic_class_count': context['synthetic_class_count'],
        'real_hkclass_metadata_class_count': context['real_class_count'],
        'real_hkclass_class_count': context['real_class_count'],
        'declared_member_count': context['declared_member_count'],
        'recovered_member_count': context['recovered_member_count'],
        'missing_real_hkclass_metadata': context['requirements'],
        'unresolved_real_metadata_counts': dict(sorted(context['unresolved_metadata_counts'].items())),
    }


@bind_archive_hkx_globals(
    'Mapping',
    '_HKX_REPRESENTATIVE_BINARY_WRITER_ROLES',
)
def _hkx_hkclass_readiness_report_2(context):
    return {
        'native_model_graph': {'status': context['native_model_graph_status'], 'rust_low_level_parse_status': 'available' if context['native_available'] else 'unavailable', 'rust_current_scope': 'sections_items_fixups_objects_native_graph' if context['native_available'] else 'not_available', 'rust_parses_sections_items_fixups_objects': context['native_available'], 'python_builds_richer_graph_export': True, 'python_richer_graph_export_scope': ['relationship graph', 'Havok-style XML object graph', 'owner-array inference', 'root recovery', 'CDMW patch/editor export'], 'native_backend_available': context['native_available'], 'native_object_records_available': context['native_object_record_count'] > 0, 'native_object_record_count': context['native_object_record_count'], 'native_fixup_sections_available': context['native_fixup_section_count'] > 0, 'native_fixup_section_count': context['native_fixup_section_count'], 'native_fixup_semantics_available': context['native_fixup_semantics_available'], 'native_object_graph_available': context['native_object_graph_available'], 'native_fixup_backed_reference_graph_available': context['native_fixup_backed_reference_graph_available'], 'native_relationship_graph_available': context['native_relationship_graph_available'], 'native_owner_array_resolution_available': context['native_owner_array_resolution_available'], 'native_root_container_semantics_available': context['native_root_container_semantics_available'], 'native_model_graph_node_count': context['native_graph_node_count'], 'native_model_graph_edge_count': context['native_graph_edge_count'], 'native_model_graph_fixup_backed_reference_edge_count': context['native_graph_fixup_edge_count'], 'native_model_graph_owner_array_count': context['native_graph_owner_array_count'], 'native_model_graph_root': context['native_graph_root'], 'native_model_graph_order': context['native_backend'].get('native_model_graph_graph_order', []), 'native_writer_model_available': context['native_no_edit_available'], 'native_no_edit_binary_writer_available': context['native_no_edit_available'], 'native_no_edit_byte_identical': context['native_no_edit_byte_identical'], 'native_no_edit_roundtrip_mode': context['native_no_edit_roundtrip_mode'], 'native_havok_xml_export_available': False, 'python_relationship_graph_node_count': context['graph_node_count'], 'python_relationship_graph_edge_count': context['graph_edge_count'], 'graph_source': 'native_model_graph_plus_python_relationship_graph' if context['native_object_graph_available'] else 'python_relationship_graph_with_native_parse_inputs' if context['native_available'] else 'python_relationship_graph', 'required_native_graph_capabilities': context['native_graph_requirements'], 'blocked_until': ['native graph fully replaces Python-only relationship export', 'native owner-array typing covers skeleton/animation/mesh containers broadly', 'native root/container semantics are proven across representative files', 'native graph can feed a byte-identical writer']},
        'biggest_remaining_gate': {'key': 'native_no_edit_read_model_write_byte_identity', 'priority': 'highest', 'status': 'file_level_passed_representative_corpus_pending' if context['native_no_edit_byte_identical'] else 'blocked', 'description': 'Biggest remaining gate before Havok-style XML can ever become importable: a native read -> model -> write path must rebuild representative HKX files byte-identically with no edits.', 'native_read_model_write_available': context['native_no_edit_available'], 'byte_identical_no_edit_rebuild_supported': context['native_no_edit_byte_identical'], 'havok_xml_import_blocked': True, 'representative_file_roles': list(_HKX_REPRESENTATIVE_BINARY_WRITER_ROLES), 'blocked_until': ['native model graph is complete enough to own records, references, arrays, and root/container semantics', 'native writer preserves section/item/fixup tables and unknown payload bytes exactly', 'representative corpus no-edit rebuilds compare byte-for-byte equal']},
        'no_edit_binary_writer': {'status': context['native_no_edit_status'], 'priority': 'biggest_remaining_gate', 'available': context['native_no_edit_available'], 'native_read_model_write_available': context['native_no_edit_available'], 'read_model_write_pipeline': context['native_no_edit_pipeline'], 'no_edit_roundtrip_mode': context['native_no_edit_roundtrip_mode'], 'byte_identical_no_edit_rebuild_supported': context['native_no_edit_byte_identical'], 'description': 'Native read -> model -> write HKX no-edit rebuilding uses a raw-preserving model for byte-identical output. Havok-style XML remains read-only until this passes representative corpus coverage and semantic object/reference rebuilding is implemented.', 'representative_file_roles': list(_HKX_REPRESENTATIVE_BINARY_WRITER_ROLES), 'requirements': context['binary_writer_requirement_rows'], 'blocked_until': ['native model graph owns all records and fixup-backed references', 'unknown payloads and padding roundtrip without normalization', 'PTCH/INDX/TPAD fixup tables roundtrip exactly', 'representative corpus byte-identity gate passes']},
        'class_internals': {'status': 'partial_synthetic_recovery', 'real_class_internals_recovered': False, 'description': 'Class-specific browsing has recovered useful fields, but full HKX parity needs more real class internals, not only synthetic hkClass member rows.', 'target_count': len(context['class_internal_targets']), 'observed_target_count': sum((1 for target in context['class_internal_targets'] if bool(target.get('present_in_file')))), 'targets': context['class_internal_targets'], 'blocked_until': ['real field layouts are confirmed per class', 'class internals are backed by native fixup/object graph references', 'arrays and nested object ownership are decoded in owner context']},
        'hard_decoder_targets': {'status': 'open_hard_decoder_targets', 'description': 'Still-hard HKX decoder areas that block full parity even after basic objects, refs, and synthetic class/member rows are readable.', 'target_count': len(context['hard_decoder_targets']), 'observed_target_count': sum((1 for target in context['hard_decoder_targets'] if bool(target.get('present_in_file')))), 'unresolved_target_count': len(context['hard_decoder_targets']), 'native_evidence_status': str(context['native_hard_internal_evidence'].get('status') or '') if isinstance(context['native_hard_internal_evidence'], Mapping) else '', 'native_total_observed_byte_count': int(context['native_hard_internal_evidence'].get('total_observed_byte_count') or 0) if isinstance(context['native_hard_internal_evidence'], Mapping) else 0, 'targets': context['hard_decoder_targets']},
        'gui_readiness': {'status': 'partial_user_friendly_modding', 'description': 'GUI readiness for making HKX modding less guesswork-heavy. This tracks visual value mapping, relationship navigation, confidence-first editing, formatting, preview feedback, and task workflows.', 'target_count': len(context['gui_targets']), 'partial_target_count': sum((1 for target in context['gui_targets'] if str(target.get('status') or '') == 'partial')), 'missing_target_count': sum((1 for target in context['gui_targets'] if str(target.get('status') or '') == 'missing')), 'targets': context['gui_targets']},
        'import_safety': {'havok_xml_types_importable': False, 'reason': 'Real hkClass metadata, native object graph semantics, hard class internals, semantic rebuilding, and representative corpus byte-identity coverage are still required.' if context['native_no_edit_byte_identical'] else 'Real hkClass metadata, native object graph semantics, hard class internals, and a no-edit binary writer are not recovered yet.'},
    }


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_native_backend_report_0(context):
    return {
        'available': bool(context['object_records'] or context['physics_tuning_groups'] or context['tagfile_reference_fixups'] or context['fixup_semantics_report'] or context['native_model_graph'] or context['hard_internal_evidence'] or context['native_real_hkclass_metadata'] or context['native_real_hkclass_metadata_v2'] or context['native_fixup_semantics_v2'] or context['native_semantic_model_v1'] or context['native_semantic_writer_gate_v1'] or context['native_edit_candidate_map_v1'] or context['native_hkx_edit_gate_v1'] or context['native_class_decoder_evidence_v2'] or context['native_decoder_evidence_v2'] or context['native_modding_readiness'] or context['no_edit_binary_writer']),
        'backend': 'native_rust_cd_hkx',
        'description': 'Optional Rust HKX parser output. The app still keeps Python decoding/import as the compatibility layer, but these native records are used to move toward a faster byte-accurate converter core.',
        'object_record_count': len(context['object_records']),
        'decoded_object_count': context['decoded_object_count'],
        'editable_object_count': context['editable_object_count'],
        'physics_tuning_group_count': len(context['physics_tuning_groups']),
        'physics_tuning_slot_count': context['tuning_slot_count'],
        'tagfile_reference_fixup_section_count': context['native_fixup_section_count'],
        'tagfile_reference_fixup_match_kind_counts': context['tagfile_reference_fixups'].get('match_kind_counts', {}),
        'tagfile_reference_fixup_reference_category_counts': context['tagfile_reference_fixups'].get('reference_category_counts', {}),
        'fixup_semantics_status': context['fixup_semantics_report'].get('status', ''),
        'fixup_semantics_ptch_tuple_shape_counts': context['fixup_semantics_report'].get('ptch_tuple_shape_counts', {}),
        'fixup_semantics_ptch_payload_match_kind_counts': context['fixup_semantics_report'].get('ptch_payload_match_kind_counts', {}),
        'fixup_semantics_remaining_case_count': len(context['fixup_semantics_report'].get('ptch_remaining_case_priorities') or []) if isinstance(context['fixup_semantics_report'].get('ptch_remaining_case_priorities'), list) else 0,
        'fixup_semantics_v2_status': context['native_fixup_semantics_v2'].get('status', ''),
        'fixup_semantics_v2_patch_site_count': int(context['native_fixup_semantics_v2'].get('patch_site_count') or 0),
        'fixup_semantics_v2_semantic_bucket_counts': dict(context['native_fixup_semantics_v2'].get('semantic_bucket_counts') or {}) if isinstance(context['native_fixup_semantics_v2'].get('semantic_bucket_counts'), Mapping) else {},
        'native_model_graph_status': context['native_model_graph'].get('status', ''),
        'native_model_graph_node_count': int(context['native_model_graph'].get('node_count') or 0),
        'native_model_graph_edge_count': int(context['native_model_graph'].get('edge_count') or 0),
        'native_model_graph_fixup_backed_reference_edge_count': int(context['native_model_graph'].get('fixup_backed_reference_edge_count') or 0),
        'native_model_graph_inferred_reference_edge_count': int(context['native_model_graph'].get('inferred_reference_edge_count') or 0),
        'native_model_graph_owner_array_count': int(context['native_model_graph'].get('owner_array_count') or 0),
        'native_model_graph_root': context['native_model_graph'].get('root', {}) if isinstance(context['native_model_graph'].get('root'), Mapping) else {},
        'native_model_graph_graph_order': list(context['native_model_graph'].get('graph_order') or []) if isinstance(context['native_model_graph'].get('graph_order'), list) else [],
        'hard_internal_evidence_status': context['hard_internal_evidence'].get('status', ''),
        'hard_internal_evidence_observed_target_count': int(context['hard_internal_evidence'].get('observed_target_count') or 0),
        'hard_internal_evidence_unresolved_target_count': int(context['hard_internal_evidence'].get('unresolved_target_count') or 0),
        'hard_internal_evidence_total_observed_byte_count': int(context['hard_internal_evidence'].get('total_observed_byte_count') or 0),
        'real_hkclass_metadata_status': context['native_real_hkclass_metadata'].get('status', ''),
        'real_hkclass_metadata_class_count': int(context['native_real_hkclass_metadata'].get('class_count') or 0),
    }


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_native_backend_report_1(context):
    return {
        'real_hkclass_metadata_member_count': int(context['native_real_hkclass_metadata'].get('member_count') or 0),
        'real_hkclass_metadata_enum_count': int(context['native_real_hkclass_metadata'].get('enum_count') or 0),
        'real_hkclass_metadata_recovered_requirements': dict(context['native_real_hkclass_metadata'].get('recovered_requirements') or {}) if isinstance(context['native_real_hkclass_metadata'].get('recovered_requirements'), Mapping) else {},
        'real_hkclass_metadata_unresolved_requirements': list(context['native_real_hkclass_metadata'].get('unresolved_requirements') or []) if isinstance(context['native_real_hkclass_metadata'].get('unresolved_requirements'), list) else [],
        'real_hkclass_metadata_v2_status': context['native_real_hkclass_metadata_v2'].get('status', ''),
        'real_hkclass_metadata_v2_class_count': int(context['native_real_hkclass_metadata_v2'].get('class_count') or 0),
        'real_hkclass_metadata_v2_member_count': int(context['native_real_hkclass_metadata_v2'].get('member_count') or 0),
        'real_hkclass_metadata_v2_synthetic_fallback_required': bool(context['native_real_hkclass_metadata_v2'].get('synthetic_fallback_required')),
        'semantic_model_v1_status': context['native_semantic_model_v1'].get('status', ''),
        'semantic_model_v1_object_count': int(context['native_semantic_model_v1'].get('object_count') or 0),
        'semantic_model_v1_field_count': int(context['native_semantic_model_v1'].get('field_count') or 0),
        'semantic_model_v1_raw_fallback_count': int(context['native_semantic_model_v1'].get('raw_fallback_count') or 0),
        'semantic_writer_gate_v1_status': context['native_semantic_writer_gate_v1'].get('status', ''),
        'semantic_writer_gate_v1_enabled': bool(context['native_semantic_writer_gate_v1'].get('enabled')),
        'semantic_writer_gate_v1_havok_xml_import_unblocked': bool(context['native_semantic_writer_gate_v1'].get('havok_xml_import_unblocked')),
        'semantic_writer_gate_v1_required_role_count': len(context['native_semantic_writer_gate_v1'].get('required_role_coverage') or []) if isinstance(context['native_semantic_writer_gate_v1'].get('required_role_coverage'), list) else 0,
        'semantic_writer_gate_v1_representative_role_gate_count': len(context['native_semantic_writer_gate_v1'].get('representative_role_gates') or []) if isinstance(context['native_semantic_writer_gate_v1'].get('representative_role_gates'), list) else 0,
        'edit_candidate_map_v1_status': context['native_edit_candidate_map_v1'].get('status', ''),
        'edit_candidate_map_v1_candidate_count': int(context['native_edit_candidate_map_v1'].get('candidate_count') or 0),
        'edit_candidate_map_v1_write_enabled_candidate_count': int(context['native_edit_candidate_map_v1'].get('write_enabled_candidate_count') or 0),
        'hkx_edit_gate_v1_status': context['native_hkx_edit_gate_v1'].get('status', ''),
        'hkx_edit_gate_v1_write_enabled_candidate_count': int(context['native_hkx_edit_gate_v1'].get('write_enabled_candidate_count') or 0),
        'hkx_edit_gate_v1_candidate_only_count': int(context['native_hkx_edit_gate_v1'].get('candidate_only_count') or 0),
        'class_decoder_evidence_v2_status': context['native_class_decoder_evidence_v2'].get('status', ''),
        'class_decoder_evidence_v2_class_status_count': int(context['native_class_decoder_evidence_v2'].get('class_status_count') or 0),
        'decoder_evidence_v2_status': context['native_decoder_evidence_v2'].get('status', ''),
        'decoder_evidence_v2_class_status_count': int(context['native_decoder_evidence_v2'].get('class_status_count') or 0),
        'decoder_evidence_v2_priority_class_count': int(context['native_decoder_evidence_v2'].get('priority_class_count') or 0),
        'decoder_evidence_v2_unresolved_or_packed_case_count': int(context['native_decoder_evidence_v2'].get('unresolved_or_packed_case_count') or 0),
        'decoder_evidence_v2_reference_semantic_counts': dict(context['native_decoder_evidence_v2'].get('reference_semantic_counts') or {}) if isinstance(context['native_decoder_evidence_v2'].get('reference_semantic_counts'), Mapping) else {},
        'decoder_evidence_v2_link_evidence_counts': dict(context['native_decoder_evidence_v2'].get('link_evidence_counts') or {}) if isinstance(context['native_decoder_evidence_v2'].get('link_evidence_counts'), Mapping) else {},
        'no_edit_binary_writer_status': context['no_edit_binary_writer'].get('status', ''),
    }


@bind_archive_hkx_globals()
def _hkx_native_backend_report_2(context):
    return {
        'no_edit_binary_writer_available': bool(context['no_edit_binary_writer'].get('available')),
        'native_read_model_write_available': bool(context['no_edit_binary_writer'].get('native_read_model_write_available')),
        'byte_identical_no_edit_rebuild_supported': bool(context['no_edit_binary_writer'].get('byte_identical_no_edit_rebuild_supported')),
        'no_edit_roundtrip_mode': str(context['no_edit_binary_writer'].get('no_edit_roundtrip_mode') or ''),
        'read_model_write_pipeline': str(context['no_edit_binary_writer'].get('read_model_write_pipeline') or ''),
        'modding_readiness_status': context['native_modding_readiness'].get('status', ''),
        'modding_readiness_per_file_label': context['native_modding_readiness'].get('per_file_label', ''),
        'modding_readiness_fixed_size_patch_importable': bool(context['native_modding_readiness'].get('fixed_size_patch_importable')),
        'modding_readiness_havok_xml_importable': bool(context['native_modding_readiness'].get('havok_xml_importable')),
        'modding_readiness_new_editable_fields_enabled': bool(context['native_modding_readiness'].get('new_editable_fields_enabled')),
        'modding_readiness_patchable_slot_count': int(context['native_modding_readiness'].get('patchable_slot_count') or 0),
        'modding_readiness_decoded_object_count': int(context['native_modding_readiness'].get('decoded_object_count') or 0),
        'modding_readiness': context['native_modding_readiness'],
        'object_records': context['object_records'][:512],
        'tagfile_reference_fixups': context['tagfile_reference_fixups'],
        'fixup_semantics_report': context['fixup_semantics_report'],
        'fixup_semantics_v2': context['native_fixup_semantics_v2'],
        'native_model_graph': context['native_model_graph'],
        'semantic_model_v1': context['native_semantic_model_v1'],
        'hard_internal_evidence': context['hard_internal_evidence'],
        'real_hkclass_metadata': context['native_real_hkclass_metadata'],
        'real_hkclass_metadata_v2': context['native_real_hkclass_metadata_v2'],
        'decoder_evidence_v2': context['native_decoder_evidence_v2'],
        'semantic_writer_gate_v1': context['native_semantic_writer_gate_v1'],
        'edit_candidate_map_v1': context['native_edit_candidate_map_v1'],
        'hkx_edit_gate_v1': context['native_hkx_edit_gate_v1'],
        'class_decoder_evidence_v2': context['native_class_decoder_evidence_v2'],
        'no_edit_binary_writer': context['no_edit_binary_writer'],
        'physics_tuning_groups': context['physics_tuning_groups'][:256],
        'truncated_object_records': max(0, len(context['object_records']) - 512),
        'truncated_physics_tuning_groups': max(0, len(context['physics_tuning_groups']) - 256),
    }


@bind_archive_hkx_globals()
def _hkx_modding_readiness_report_0(context):
    return {
        'format': 'cdmw_hkx_modding_readiness_v1',
        'native_format': str(context['native_readiness'].get('format') or ''),
        'status': context['status'],
        'source': 'native_rust_cd_hkx' if context['native_readiness'] else 'python_converter_report',
        'imported': False,
        'read_only': True,
        'per_file_label': context['per_file_label'],
        'readiness_labels': context['labels'],
        'fixed_size_patch_importable': context['fixed_size_patch_importable'],
        'havok_xml_importable': context['havok_xml_importable'],
        'new_editable_fields_enabled': False,
    }


@bind_archive_hkx_globals(
)
def _hkx_modding_readiness_report_1(context):
    return {
        'decoded_object_count': context['decoded_object_count'],
        'patchable_slot_count': context['patchable_slot_count'],
        'fixup_backed_reference_edge_count': int(context['native_backend'].get('native_model_graph_fixup_backed_reference_edge_count') or 0),
        'owner_array_count': int(context['native_backend'].get('native_model_graph_owner_array_count') or 0),
        'unresolved_or_packed_case_count': int(context['decoder_evidence_v2'].get('unresolved_or_packed_case_count') or 0),
        'modding_path': 'CDMW fixed-size patch XML/JSON only',
        'havok_xml_policy': 'read_only_view',
        'description': 'Per-file HKX modding readiness. This labels what can be patched today and what is only decoded evidence; it does not make Havok XML importable.',
        'semantic_writer_gate': {'status': str(context['gate'].get('status') or 'disabled_pending_semantic_rebuild'), 'mode': str(context['gate'].get('mode') or 'fixed_size_patch_only'), 'enabled': False, 'raw_preserving_no_edit_writer_required': True, 'semantic_rebuild_supported': context['semantic_rebuild_supported'], 'fixed_size_value_edits_allowed': True, 'havok_xml_import_unblocked': False, 'no_edit_binary_writer_status': str(context['no_edit_writer'].get('status') or 'not_started'), 'byte_identical_no_edit_rebuild_supported': context['byte_identical_no_edit'], 'read_model_write_pipeline': str(context['no_edit_writer'].get('read_model_write_pipeline') or ''), 'allowed_edits': [str(edit) for edit in context['allowed_edits']] or ['existing fixed-size CDMW patch rows'], 'blocked_edits': [str(edit) for edit in context['blocked_edits']] or ['Havok XML import', 'array count edits', 'reference edits', 'string edits', 'mesh topology edits', 'semantic object graph rebuild'], 'requirements': [str(requirement) for requirement in context['requirements']] or ['byte-identical no-edit rebuild across representative corpus', 'fixup-backed object/data/string/type reference semantics', 'owner-array element typing', 'root/container/named-variant semantics', 'fixed-edit byte identity tests']},
        'external_tool_references': [{'name': 'hkxcmd', 'use': 'XML/KF workflow terminology reference', 'limitation': 'Targets Skyrim-era Havok 2010.2; not a direct Crimson Desert tagfile rebuild path.', 'integration': 'optional_reference_only'}, {'name': 'HKXPack', 'use': 'TagXML formatting and parity comparison reference', 'limitation': 'Targets Fallout 4 Havok 2014.1; useful for format ideas, not direct import support.', 'integration': 'optional_reference_only'}, {'name': 'HavokLib', 'use': 'Animation/root/container class metadata reference', 'limitation': 'No tagfile support and GPL licensing; do not copy code into CDMW.', 'integration': 'metadata_reference_only'}, {'name': 'serde-hkx CLI', 'use': 'Byte-diff, dependency-tree, and debug UX reference', 'limitation': 'External comparison idea only; CDMW keeps its Crimson Desert decoder native.', 'integration': 'optional_reference_only'}, {'name': 'Blender HKX / DSAnimStudio-style UX', 'use': 'Skeleton and animation browsing workflow reference', 'limitation': 'UX reference only; physics/tagfile decoder stays CDMW-native.', 'integration': 'ux_reference_only'}],
        'task_groups': context['task_groups'],
    }
