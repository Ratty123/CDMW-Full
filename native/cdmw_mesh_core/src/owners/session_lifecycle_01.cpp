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
        // Every editable original submesh starts as its own provenance: each
        // vertex is one original parent at weight 1, each triangle is its own
        // original face. Every later topology edit folds onto this anchor.
        // A submesh that arrived carrying a valid contract keeps it: reopening a
        // session on already-edited geometry must not relabel that geometry as
        // its own original.
        if (!mesh_editor_topology_provenance_shape_valid(submesh)) {
            mesh_editor_initialize_identity_topology_provenance(submesh);
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
    out << ",\"capabilities\":[";
    write_escaped(out, MESH_TOPOLOGY_PROVENANCE_CAPABILITY);
    out << "],\"topology_contract\":";
    write_escaped(out, MESH_TOPOLOGY_PROVENANCE_VERSION);
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

void mesh_editor_filter_selection_to_submeshes(
    MeshEditorSelection& selection,
    const std::set<int>& allowed
) {
    if (allowed.empty()) return;
    for (auto* mapping : {&selection.vertices, &selection.faces}) {
        for (auto item = mapping->begin(); item != mapping->end();) {
            item = allowed.find(item->first) == allowed.end() ? mapping->erase(item) : std::next(item);
        }
    }
    for (auto item = selection.vertex_weights.begin(); item != selection.vertex_weights.end();) {
        item = allowed.find(item->first) == allowed.end() ? selection.vertex_weights.erase(item) : std::next(item);
    }
    for (auto item = selection.edges.begin(); item != selection.edges.end();) {
        item = allowed.find(item->first) == allowed.end() ? selection.edges.erase(item) : std::next(item);
    }
    for (auto item = selection.source_indices.begin(); item != selection.source_indices.end();) {
        item = allowed.find(*item) == allowed.end() ? selection.source_indices.erase(item) : std::next(item);
    }
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
    const std::string target_mode = lower_ascii(string_or(
        raw_selection != nullptr ? raw_selection->get("target_mode") : nullptr,
        string_or(root.get("target_mode"), "vertex")
    ));
    const bool context_operation = selection_operation == "context";
    const int source_pick_count = context_operation ? static_cast<int>(incoming.source_indices.size()) : -1;
    bool selection_changed = true;
    if (selection_operation == "grow" || selection_operation == "shrink" || selection_operation == "smooth"
        || selection_operation == "all" || selection_operation == "invert") {
        const int iterations = std::max(
            0,
            int_or(root.get("iterations"), raw_selection != nullptr ? int_or(raw_selection->get("iterations"), 1) : 1)
        );
        session.selection = mesh_editor_apply_selection_edit(
            session,
            incoming,
            selection_operation,
            target_mode,
            iterations
        );
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
    if (raw_selection != nullptr && raw_selection->type == JsonValue::Type::Object) {
        mesh_editor_filter_selection_to_submeshes(
            session.selection,
            mesh_editor_indices_from_json(raw_selection->get("allowed_submesh_indices"))
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
