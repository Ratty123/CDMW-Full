struct MeshEditorHistoryReportState {
    std::string command;
    std::string operation;
    std::string delta_output_dir;
    std::string session_id;
    bool topology_changed = false;
    bool normal = false;
    bool tangent = false;
    bool uv = false;
    bool material = false;
    std::vector<SubmeshMeshEditResult> results;
    std::vector<SubmeshNormalsResult> normal_results;
    std::vector<SubmeshTangentsResult> tangent_results;
    std::vector<SubmeshUvTransformResult> uv_results;
    std::set<int> affected_indices;
};

void mesh_editor_append_history_report(
    MeshEditorHistoryReportState& state,
    int index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored
) {
    if (state.normal) {
        state.normal_results.push_back(mesh_editor_normal_history_report_result(
            index, current, restored, state.operation, state.delta_output_dir, state.session_id
        ));
    } else if (state.uv) {
        state.uv_results.push_back(mesh_editor_uv_history_report_result(
            index, current, restored, state.delta_output_dir, state.session_id
        ));
    } else if (state.tangent) {
        state.tangent_results.push_back(mesh_editor_tangent_history_report_result(
            index, current, restored, state.delta_output_dir, state.session_id
        ));
    } else {
        state.results.push_back(mesh_editor_history_report_result(
            index,
            current,
            restored,
            state.material ? state.operation : state.command,
            state.topology_changed,
            state.delta_output_dir,
            state.session_id
        ));
    }
}

void mesh_editor_apply_topology_history(
    MeshEditorHistoryEntry& entry,
    MeshEditorSession& session,
    MeshEditorHistoryReportState& state
) {
    std::map<int, MeshSessionSubmesh>& submeshes = mesh_editor_submeshes(session);
    std::map<int, MeshSessionSubmesh> restored_submeshes = std::move(entry.before);
    std::set<int> absent_submeshes = std::move(entry.absent_before);
    std::map<int, MeshSessionSubmesh> reverse_submeshes;
    std::set<int> reverse_absent;
    std::set<int> topology_indices = absent_submeshes;
    for (const auto& restored : restored_submeshes) {
        topology_indices.insert(restored.first);
    }
    for (const int index : topology_indices) {
        const auto current = submeshes.find(index);
        if (current == submeshes.end()) {
            reverse_absent.insert(index);
        } else {
            reverse_submeshes[index] = current->second;
        }
    }
    for (const auto& restored : restored_submeshes) {
        state.affected_indices.insert(restored.first);
        const auto current = submeshes.find(restored.first);
        if (current != submeshes.end()) {
            mesh_editor_append_history_report(state, restored.first, current->second, restored.second);
            continue;
        }
        SubmeshMeshEditResult appended = mesh_editor_history_report_result(
            restored.first,
            MeshSessionSubmesh{},
            restored.second,
            state.material ? state.operation : state.command,
            true,
            state.delta_output_dir,
            state.session_id
        );
        appended.append_submesh = true;
        const auto source = entry.append_source_indices.find(restored.first);
        appended.source_index = source != entry.append_source_indices.end() ? source->second : restored.first;
        appended.name_suffix = " restored";
        state.results.push_back(std::move(appended));
    }
    for (const int index : absent_submeshes) {
        state.affected_indices.insert(index);
        submeshes.erase(index);
    }
    mesh_editor_restore_submeshes(session, restored_submeshes);
    entry.before = std::move(reverse_submeshes);
    entry.absent_before = std::move(reverse_absent);
}

std::vector<Vec3> mesh_editor_history_current_positions(
    const MeshSessionSubmesh& submesh,
    const MeshEditorSubmeshDelta& delta
) {
    std::vector<Vec3> positions;
    positions.reserve(delta.vertices.indices.size());
    for (const int vertex_index : delta.vertices.indices) {
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= submesh.vertices.size()) {
            throw std::runtime_error("mesh editor sparse history vertex is out of range");
        }
        positions.push_back(submesh.vertices[static_cast<std::size_t>(vertex_index)]);
    }
    return positions;
}

void mesh_editor_apply_sparse_history(
    const MeshEditorHistoryEntry& entry,
    MeshEditorSession& session,
    MeshEditorHistoryReportState& state
) {
    const bool restore_before = state.command == "undo";
    std::map<int, MeshSessionSubmesh>& submeshes = mesh_editor_submeshes(session);
    for (const auto& item : entry.deltas) {
        auto current = submeshes.find(item.first);
        if (current == submeshes.end()) {
            throw std::runtime_error("mesh editor sparse history submesh is missing");
        }
        if (state.operation == "transform" || state.operation == "brush") {
            std::vector<Vec3> before_positions = mesh_editor_history_current_positions(current->second, item.second);
            mesh_editor_apply_submesh_delta(current->second, item.second, restore_before);
            state.affected_indices.insert(item.first);
            state.results.push_back(mesh_editor_sparse_position_history_result(
                item.first,
                current->second,
                item.second,
                std::move(before_positions),
                state.command,
                state.delta_output_dir,
                state.session_id
            ));
            continue;
        }
        MeshSessionSubmesh restored = current->second;
        mesh_editor_apply_submesh_delta(restored, item.second, restore_before);
        state.affected_indices.insert(item.first);
        mesh_editor_append_history_report(state, item.first, current->second, restored);
        current->second = std::move(restored);
    }
}

std::string mesh_editor_history_edit_report(const MeshEditorHistoryReportState& state) {
    if (state.normal) {
        return normals_report_json(state.normal_results, state.operation);
    }
    if (state.uv) {
        return uv_transform_report_json(state.uv_results);
    }
    if (state.tangent) {
        return tangents_report_json(state.tangent_results);
    }
    return mesh_edit_report_json(state.results);
}

std::size_t mesh_editor_history_result_count(const MeshEditorHistoryReportState& state) {
    if (state.normal) return state.normal_results.size();
    if (state.uv) return state.uv_results.size();
    if (state.tangent) return state.tangent_results.size();
    return state.results.size();
}

std::string mesh_editor_history_report_json(
    const MeshEditorHistoryReportState& state,
    const MeshEditorSession& session,
    const std::string& edit_report,
    bool include_edit_report,
    double cpp_ms,
    double io_serialization_ms
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":";
    write_escaped(out, state.command);
    out << ",\"session_id\":";
    write_escaped(out, state.session_id);
    out << ",\"affected_submesh_indices\":[";
    bool wrote = false;
    for (const int index : state.affected_indices) {
        if (wrote) out << ',';
        wrote = true;
        out << index;
    }
    out << "],\"topology_changed\":" << (state.topology_changed ? "true" : "false")
        << ",\"result_count\":" << mesh_editor_history_result_count(state) << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    mesh_editor_write_submesh_summaries(out, session);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms, io_serialization_ms);
    if (include_edit_report) {
        out << ",\"edit_report\":" << edit_report;
    }
    out << "}";
    return out.str();
}

std::string mesh_editor_history_session_report(
    const std::string& command,
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    std::vector<MeshEditorHistoryEntry>& from_stack = command == "undo" ? session.undo_stack : session.redo_stack;
    std::vector<MeshEditorHistoryEntry>& to_stack = command == "undo" ? session.redo_stack : session.undo_stack;
    if (from_stack.empty()) {
        throw std::runtime_error("mesh editor history is empty");
    }
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    const bool include_edit_report = bool_or(root.get("include_edit_report"), !delta_output_dir.empty());
    MeshEditorHistoryEntry entry = std::move(from_stack.back());
    from_stack.pop_back();
    MeshEditorHistoryReportState state;
    state.command = command;
    state.operation = entry.operation;
    state.delta_output_dir = delta_output_dir;
    state.session_id = session_id;
    state.topology_changed = entry.topology_changed;
    state.normal = mesh_editor_is_normal_operation(state.operation);
    state.tangent = mesh_editor_is_tangent_operation(state.operation) && !state.topology_changed;
    state.uv = mesh_editor_is_uv_operation(state.operation) && !state.topology_changed;
    state.material = state.operation == "material_assign" || state.operation == "material_copy";
    if (state.topology_changed) {
        mesh_editor_apply_topology_history(entry, session, state);
    } else {
        mesh_editor_apply_sparse_history(entry, session, state);
    }
    if (entry.morph_state_changed) {
        const std::shared_ptr<const MeshMorphRuntime>& restore = command == "undo"
            ? entry.morph_before
            : entry.morph_after;
        session.morph = std::make_shared<MeshMorphRuntime>(restore ? *restore : MeshMorphRuntime{});
        session.morph->state_revision = ++session.morph_state_revision;
    }
    mesh_editor_push_history(to_stack, std::move(entry));
    mesh_editor_trim_session_history(session);
    if (state.topology_changed) {
        ++session.topology_revision;
        session.selection = MeshEditorSelection{};
        ++session.selection_revision;
    }
    ++session.edit_revision;
    const auto report_started = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
    const std::string edit_report = include_edit_report ? mesh_editor_history_edit_report(state) : std::string();
    const auto report_finished = std::chrono::steady_clock::now();
    const double io_ms = std::chrono::duration<double, std::milli>(report_finished - report_started).count();
    return mesh_editor_history_report_json(
        state, session, edit_report, include_edit_report, cpp_ms, io_ms
    );
}
