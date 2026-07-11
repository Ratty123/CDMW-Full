std::string mesh_editor_open_session_report(
    const JsonValue& root,
    const std::string& session_id,
    const std::string& native_session_id,
    const std::chrono::steady_clock::time_point& started
) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing mesh editor submeshes");
    }
    MeshEditorSession editor_session;
    editor_session.native_session_id = native_session_id;
    std::map<int, MeshSessionSubmesh>& editor_submeshes = g_mesh_sessions[native_session_id];
    editor_submeshes.clear();
    int stored = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        MeshSessionSubmesh submesh = mesh_session_submesh_from_item(item);
        if (submesh.vertices.empty()) {
            continue;
        }
        editor_submeshes[index] = std::move(submesh);
        ++stored;
    }
    if (stored <= 0) {
        throw std::runtime_error("mesh editor open stored no submeshes");
    }
    g_mesh_editor_sessions[session_id] = std::move(editor_session);

    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"open\",\"session_id\":";
    write_escaped(out, session_id);
    out << ',';
    mesh_editor_write_session_counts(out, g_mesh_editor_sessions[session_id]);
    out << ',';
    mesh_editor_write_submesh_summaries(out, g_mesh_editor_sessions[session_id]);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string mesh_editor_close_session_report(
    const std::string& session_id,
    const std::string& native_session_id,
    const std::chrono::steady_clock::time_point& started
) {
    g_mesh_editor_sessions.erase(session_id);
    g_mesh_sessions.erase(native_session_id);
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"close\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"submesh_count\":0,";
    mesh_editor_write_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string mesh_editor_summary_report(
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"summary\",\"session_id\":";
    write_escaped(out, session_id);
    out << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    mesh_editor_write_submesh_summaries(out, session);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string mesh_editor_select_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const JsonValue* raw_selection = root.get("selection");
    std::string selection_operation = string_or(root.get("selection_operation"), string_or(root.get("operation"), ""));
    if (selection_operation.empty() && raw_selection != nullptr) {
        selection_operation = string_or(raw_selection->get("operation"), string_or(raw_selection->get("selection_operation"), "replace"));
    }
    selection_operation = lower_ascii(selection_operation.empty() ? "replace" : selection_operation);
    const MeshEditorSelection incoming = mesh_editor_selection_from_json(raw_selection, &session);
    const bool context_operation = selection_operation == "context";
    const int source_pick_count = context_operation ? static_cast<int>(incoming.source_indices.size()) : -1;
    bool selection_changed = true;
    if (selection_operation == "grow" || selection_operation == "shrink" || selection_operation == "smooth"
        || selection_operation == "all" || selection_operation == "invert") {
        const int iterations = std::max(
            0,
            int_or(root.get("iterations"), raw_selection != nullptr ? int_or(raw_selection->get("iterations"), 1) : 1)
        );
        session.selection = mesh_editor_apply_selection_edit(session, incoming, selection_operation, iterations);
    } else if (context_operation) {
        if (mesh_editor_selection_empty(incoming)) {
            selection_changed = false;
        } else {
            session.selection = mesh_editor_prune_and_combine_selection(session, incoming, "replace");
        }
    } else {
        session.selection = mesh_editor_prune_and_combine_selection(
            session,
            incoming,
            normalized_selection_operation(selection_operation)
        );
    }
    if (selection_changed) {
        ++session.selection_revision;
    }
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    return mesh_editor_select_report_json(
        session,
        session_id,
        selection_operation,
        string_or(root.get("selection_output_dir"), ""),
        cpp_ms,
        source_pick_count
    );
}
