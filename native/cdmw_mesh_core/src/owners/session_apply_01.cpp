std::string mesh_editor_apply_edit_report(const MeshEditorApplyState& state) {
    if (!state.include_edit_report) {
        return {};
    }
    if (state.normal_operation) {
        return normals_report_json(state.normal_results, state.operation);
    }
    if (state.uv_operation) {
        return state.auto_uv_operation
            ? mesh_edit_report_json(state.results, state.include_preview_deltas)
            : uv_transform_report_json(state.uv_results);
    }
    if (state.tangent_operation) {
        return tangents_report_json(state.tangent_results);
    }
    return mesh_edit_report_json(state.results, state.include_preview_deltas);
}

std::size_t mesh_editor_apply_result_count(const MeshEditorApplyState& state) {
    if (state.normal_operation) return state.normal_results.size();
    if (state.uv_operation) return state.auto_uv_operation ? state.results.size() : state.uv_results.size();
    if (state.tangent_operation) return state.tangent_results.size();
    return state.results.size();
}

std::string mesh_editor_apply_report_json(
    const std::string& session_id,
    const MeshEditorSession& session,
    const MeshEditorApplyState& state,
    const std::string& edit_report,
    bool response_stroke_active,
    double cpp_ms,
    double io_serialization_ms
) {
    const bool topology_changed = !state.affected_indices.empty() && state.applied_topology_changed;
    const std::size_t sparse_updates = static_cast<std::size_t>(std::count_if(
        state.results.begin(),
        state.results.end(),
        [](const SubmeshMeshEditResult& result) { return result.resident_sparse; }
    ));
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"apply\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"affected_submesh_indices\":[";
    bool wrote = false;
    for (const int index : state.affected_indices) {
        if (wrote) out << ',';
        wrote = true;
        out << index;
    }
    out << "],\"topology_changed\":" << (topology_changed ? "true" : "false")
        << ",\"result_count\":" << mesh_editor_apply_result_count(state)
        << ",\"resident_sparse_update_count\":" << sparse_updates << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    mesh_editor_write_submesh_summaries(out, session);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms, io_serialization_ms);
    if (state.include_edit_report) {
        out << ",\"edit_report\":" << edit_report;
    }
    if (!state.stroke_phase.empty()) {
        out << ",\"stroke\":{\"phase\":";
        write_escaped(out, state.stroke_phase);
        out << ",\"stroke_id\":";
        write_escaped(out, state.stroke_id);
        out << ",\"operation\":";
        write_escaped(out, state.operation);
        out << ",\"active\":" << (response_stroke_active ? "true" : "false")
            << ",\"update_count\":" << state.response_stroke_update_count
            << ",\"history_coalesced\":" << (state.history_coalesced ? "true" : "false") << "}";
    }
    out << "}";
    return out.str();
}

std::string mesh_editor_apply_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const JsonValue* edit = root.get("edit");
    if (edit == nullptr || edit->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing mesh editor edit object");
    }
    (void)mesh_editor_submeshes(session);
    MeshEditorApplyState state;
    state.delta_output_dir = string_or(root.get("delta_output_dir"), "");
    state.include_edit_report = bool_or(root.get("include_edit_report"), !state.delta_output_dir.empty());
    state.include_preview_deltas = bool_or(root.get("include_preview_deltas"), true);
    state.operation = lower_ascii(string_or(edit->get("operation"), string_or(root.get("operation"), "")));
    state.stroke_phase = mesh_editor_stroke_phase_from_json(root, *edit);
    mesh_editor_validate_apply_stroke(state.operation, state.stroke_phase);
    state.stroke_id = mesh_editor_prepare_apply_stroke(
        root, *edit, session, state.operation, state.stroke_phase
    );
    std::map<int, MeshSessionSubmesh>& native_session = mesh_editor_submeshes(session);
    if (state.stroke_phase == "cancel") {
        const MeshEditorCancelState cancel = mesh_editor_cancel_active_stroke(
            session, native_session, state, session_id
        );
        return mesh_editor_cancel_stroke_report_json(session_id, session, state, cancel, started);
    }
    mesh_editor_initialize_apply_operation(
        session_id,
        mesh_editor_native_session_id(session_id),
        session,
        *edit,
        native_session,
        state
    );
    if (mesh_editor_morph_topology_blocked(session)
        && mesh_editor_apply_needs_topology_history(session, state)) {
        throw std::runtime_error("Bake or Reset active procedural sliders before a topology edit");
    }
    mesh_editor_execute_apply_operation(session, *edit, native_session, state);
    mesh_editor_commit_apply_results(session, native_session, state);
    bool response_stroke_active = session.active_stroke.active;
    if (state.stroke_phase == "end") {
        session.active_stroke = MeshEditorStroke{};
        response_stroke_active = false;
        ++session.stroke_revision;
    }
    const auto report_started = std::chrono::steady_clock::now();
    const std::string edit_report = mesh_editor_apply_edit_report(state);
    const auto report_finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
    const double io_ms = std::chrono::duration<double, std::milli>(report_finished - report_started).count();
    return mesh_editor_apply_report_json(
        session_id, session, state, edit_report, response_stroke_active, cpp_ms, io_ms
    );
}
