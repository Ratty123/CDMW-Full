use crate::*;

pub(crate) fn push_json_string_array(out: &mut String, values: &[String]) {
    out.push('[');
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(out, "\"{}\"", json_escape(value));
    }
    out.push(']');
}

pub(crate) fn push_hkx_modding_readiness_json(out: &mut String, report: &HkxModdingReadiness) {
    let _ = write!(
        out,
        "{{\"format\":\"{}\",\"status\":\"{}\",\"imported\":{},\"read_only\":{},\"per_file_label\":\"{}\",\"fixed_size_patch_importable\":{},\"havok_xml_importable\":{},\"new_editable_fields_enabled\":{},\"decoded_object_count\":{},\"patchable_slot_count\":{},\"fixup_backed_reference_edge_count\":{},\"owner_array_count\":{},\"unresolved_or_packed_case_count\":{}",
        json_escape(&report.format),
        json_escape(&report.status),
        json_bool(report.imported),
        json_bool(report.read_only),
        json_escape(&report.per_file_label),
        json_bool(report.fixed_size_patch_importable),
        json_bool(report.havok_xml_importable),
        json_bool(report.new_editable_fields_enabled),
        report.decoded_object_count,
        report.patchable_slot_count,
        report.fixup_backed_reference_edge_count,
        report.owner_array_count,
        report.unresolved_or_packed_case_count
    );
    out.push_str(",\"readiness_labels\":");
    push_json_string_array(out, &report.readiness_labels);
    out.push_str(",\"semantic_writer_gate\":");
    let gate = &report.semantic_writer_gate;
    let _ = write!(
        out,
        "{{\"status\":\"{}\",\"mode\":\"{}\",\"enabled\":{},\"raw_preserving_no_edit_writer_required\":{},\"semantic_rebuild_supported\":{},\"fixed_size_value_edits_allowed\":{}",
        json_escape(&gate.status),
        json_escape(&gate.mode),
        json_bool(gate.enabled),
        json_bool(gate.raw_preserving_no_edit_writer_required),
        json_bool(gate.semantic_rebuild_supported),
        json_bool(gate.fixed_size_value_edits_allowed)
    );
    out.push_str(",\"allowed_edits\":");
    push_json_string_array(out, &gate.allowed_edits);
    out.push_str(",\"blocked_edits\":");
    push_json_string_array(out, &gate.blocked_edits);
    out.push_str(",\"requirements\":");
    push_json_string_array(out, &gate.requirements);
    out.push_str("},\"task_groups\":[");
    for (index, group) in report.task_groups.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        let _ = write!(
            out,
            "{{\"key\":\"{}\",\"label\":\"{}\",\"readiness_label\":\"{}\",\"patchable_slot_count\":{},\"context_record_count\":{},\"risk\":\"{}\",\"import_safe\":{},\"description\":\"{}\",\"evidence\":",
            json_escape(&group.key),
            json_escape(&group.label),
            json_escape(&group.readiness_label),
            group.patchable_slot_count,
            group.context_record_count,
            json_escape(&group.risk),
            json_bool(group.import_safe),
            json_escape(&group.description)
        );
        push_json_string_array(out, &group.evidence);
        out.push('}');
    }
    out.push_str("]}");
}
