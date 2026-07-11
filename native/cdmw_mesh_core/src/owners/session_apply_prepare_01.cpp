struct MeshEditorApplyState {
    std::string delta_output_dir;
    std::string operation;
    std::string stroke_phase;
    std::string stroke_id;
    bool include_edit_report = false;
    bool include_preview_deltas = true;
    bool normal_operation = false;
    bool tangent_operation = false;
    bool uv_operation = false;
    bool auto_uv_operation = false;
    bool material_operation = false;
    bool cleanup_operation = false;
    bool delete_parts_operation = false;
    bool record_history = true;
    JsonValue edit_root;
    MeshEditorHistoryEntry history;
    std::map<int, MeshSessionSubmesh> pre_edit_submeshes;
    std::map<int, MeshEditorPreEditChannels> pre_edit_channels;
    std::set<int> candidate_indices;
    std::vector<SubmeshMeshEditResult> results;
    std::vector<SubmeshNormalsResult> normal_results;
    std::vector<SubmeshTangentsResult> tangent_results;
    std::vector<SubmeshUvTransformResult> uv_results;
    std::set<int> affected_indices;
    std::set<int> existing_result_indices;
    bool history_coalesced = false;
    int response_stroke_update_count = 0;
    bool applied_topology_changed = false;
};

struct MeshEditorCancelState {
    std::set<int> affected_indices;
    std::vector<SubmeshMeshEditResult> results;
    bool topology_changed = false;
    bool cancelled_history = false;
};

void mesh_editor_validate_apply_stroke(
    const std::string& operation,
    const std::string& stroke_phase
) {
    if (!mesh_editor_valid_stroke_phase(stroke_phase)) {
        throw std::runtime_error("unsupported mesh editor stroke phase: " + stroke_phase);
    }
    if (!stroke_phase.empty() && !mesh_editor_is_live_stroke_operation(operation)) {
        throw std::runtime_error("mesh editor stroke phase requires brush or transform operation");
    }
}

std::string mesh_editor_prepare_apply_stroke(
    const JsonValue& root,
    const JsonValue& edit,
    MeshEditorSession& session,
    const std::string& operation,
    const std::string& stroke_phase
) {
    if (root.get("selection") != nullptr) {
        session.selection = mesh_editor_selection_from_json(root.get("selection"), &session);
        ++session.selection_revision;
    }
    std::string stroke_id = mesh_editor_stroke_id_from_json(root, edit);
    if (stroke_phase == "begin") {
        if (session.active_stroke.active) {
            throw std::runtime_error("mesh editor stroke is already active");
        }
        if (stroke_id.empty()) {
            stroke_id = operation + "-" + std::to_string(session.stroke_revision + 1);
        }
        session.active_stroke = MeshEditorStroke{};
        session.active_stroke.active = true;
        session.active_stroke.stroke_id = stroke_id;
        session.active_stroke.operation = operation;
        session.active_stroke.tool = mesh_editor_tool_from_edit(edit);
        ++session.stroke_revision;
    } else if (stroke_phase == "update" || stroke_phase == "end" || stroke_phase == "cancel") {
        if (stroke_id.empty() && session.active_stroke.active) {
            stroke_id = session.active_stroke.stroke_id;
        }
        if (!session.active_stroke.active || stroke_id.empty() || session.active_stroke.stroke_id != stroke_id) {
            throw std::runtime_error("mesh editor stroke phase requires matching active stroke");
        }
    }
    return stroke_id;
}

void mesh_editor_cancel_topology_history(
    MeshEditorSession& session,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorHistoryEntry& entry,
    const MeshEditorApplyState& apply,
    const std::string& session_id,
    MeshEditorCancelState& cancel
) {
    for (const auto& restored : entry.before) {
        cancel.affected_indices.insert(restored.first);
        const auto current = native_session.find(restored.first);
        if (current != native_session.end()) {
            cancel.results.push_back(mesh_editor_history_report_result(
                restored.first,
                current->second,
                restored.second,
                "cancel",
                true,
                apply.delta_output_dir,
                session_id
            ));
        }
    }
    for (const int index : entry.absent_before) {
        cancel.affected_indices.insert(index);
        native_session.erase(index);
    }
    mesh_editor_restore_submeshes(session, entry.before);
}

void mesh_editor_cancel_sparse_history(
    std::map<int, MeshSessionSubmesh>& native_session,
    const MeshEditorHistoryEntry& entry,
    const MeshEditorApplyState& apply,
    const std::string& session_id,
    MeshEditorCancelState& cancel
) {
    for (const auto& item : entry.deltas) {
        auto current = native_session.find(item.first);
        if (current == native_session.end()) {
            throw std::runtime_error("mesh editor sparse stroke history submesh is missing");
        }
        std::vector<Vec3> before_positions = mesh_editor_history_current_positions(
            current->second, item.second
        );
        mesh_editor_apply_submesh_delta(current->second, item.second, true);
        cancel.affected_indices.insert(item.first);
        cancel.results.push_back(mesh_editor_sparse_position_history_result(
            item.first,
            current->second,
            item.second,
            std::move(before_positions),
            "cancel",
            apply.delta_output_dir,
            session_id
        ));
    }
}

MeshEditorCancelState mesh_editor_cancel_active_stroke(
    MeshEditorSession& session,
    std::map<int, MeshSessionSubmesh>& native_session,
    const MeshEditorApplyState& apply,
    const std::string& session_id
) {
    MeshEditorCancelState cancel;
    if (!session.undo_stack.empty() && session.undo_stack.back().stroke_id == apply.stroke_id) {
        MeshEditorHistoryEntry entry = std::move(session.undo_stack.back());
        session.undo_stack.pop_back();
        cancel.topology_changed = entry.topology_changed;
        if (cancel.topology_changed) {
            mesh_editor_cancel_topology_history(session, native_session, entry, apply, session_id, cancel);
            ++session.topology_revision;
            session.selection = MeshEditorSelection{};
            ++session.selection_revision;
        } else {
            mesh_editor_cancel_sparse_history(native_session, entry, apply, session_id, cancel);
        }
        ++session.edit_revision;
        cancel.cancelled_history = true;
    }
    session.active_stroke = MeshEditorStroke{};
    ++session.stroke_revision;
    return cancel;
}

std::string mesh_editor_cancel_stroke_report_json(
    const std::string& session_id,
    const MeshEditorSession& session,
    const MeshEditorApplyState& apply,
    const MeshEditorCancelState& cancel,
    const std::chrono::steady_clock::time_point& started
) {
    const auto report_started = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
    const std::string edit_report = apply.include_edit_report
        ? mesh_edit_report_json(cancel.results, apply.include_preview_deltas)
        : std::string();
    const auto report_finished = std::chrono::steady_clock::now();
    const double io_ms = std::chrono::duration<double, std::milli>(report_finished - report_started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"apply\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"affected_submesh_indices\":[";
    bool wrote = false;
    for (const int index : cancel.affected_indices) {
        if (wrote) out << ',';
        wrote = true;
        out << index;
    }
    out << "],\"topology_changed\":" << (cancel.topology_changed ? "true" : "false")
        << ",\"result_count\":" << cancel.results.size() << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    mesh_editor_write_submesh_summaries(out, session);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms, io_ms);
    if (apply.include_edit_report) {
        out << ",\"edit_report\":" << edit_report;
    }
    out << ",\"stroke\":{\"phase\":\"cancel\",\"stroke_id\":";
    write_escaped(out, apply.stroke_id);
    out << ",\"operation\":";
    write_escaped(out, apply.operation);
    out << ",\"active\":false,\"update_count\":0,\"history_cancelled\":"
        << (cancel.cancelled_history ? "true" : "false") << "}}";
    return out.str();
}

std::set<int> mesh_editor_apply_history_candidates(
    const MeshEditorSession& session,
    const std::map<int, MeshSessionSubmesh>& native_session,
    const MeshEditorApplyState& state
) {
    std::set<int> candidates = session.selection.source_indices;
    for (const auto& mapping : {session.selection.vertices, session.selection.faces}) {
        for (const auto& item : mapping) candidates.insert(item.first);
    }
    for (const auto& item : session.selection.edges) candidates.insert(item.first);
    if (state.material_operation) {
        candidates = mesh_editor_material_candidate_indices(session);
    }
    if (candidates.empty() && state.operation != "transform") {
        for (const auto& item : native_session) candidates.insert(item.first);
    }
    return candidates;
}

void mesh_editor_filter_apply_root_to_candidates(MeshEditorApplyState& state) {
    const JsonValue* submeshes = state.edit_root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        return;
    }
    JsonValue filtered;
    filtered.type = JsonValue::Type::Array;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (state.candidate_indices.find(index) != state.candidate_indices.end()) {
            filtered.array_value.push_back(item);
        }
    }
    state.edit_root.object_value["submeshes"] = std::move(filtered);
}

bool mesh_editor_apply_needs_topology_history(
    const MeshEditorSession& session,
    const MeshEditorApplyState& state
) {
    return state.auto_uv_operation
        || state.cleanup_operation
        || state.delete_parts_operation
        || (state.material_operation && mesh_editor_material_has_component_selection(session))
        || (
            state.operation != "transform"
            && state.operation != "brush"
            && !state.normal_operation
            && !state.tangent_operation
            && !state.uv_operation
            && !state.material_operation
        );
}

void mesh_editor_capture_apply_history(
    MeshEditorSession& session,
    const JsonValue& edit,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    state.candidate_indices = mesh_editor_apply_history_candidates(session, native_session, state);
    mesh_editor_filter_apply_root_to_candidates(state);
    if (!state.record_history) {
        return;
    }
    const bool topology_candidate = mesh_editor_apply_needs_topology_history(session, state);
    for (const int index : state.candidate_indices) {
        const auto found = native_session.find(index);
        if (found == native_session.end()) {
            continue;
        }
        if (topology_candidate) {
            state.pre_edit_submeshes[index] = found->second;
        }
        if (topology_candidate && !state.auto_uv_operation && !state.material_operation) {
            continue;
        }
        const bool transform = state.operation == "transform";
        state.pre_edit_channels[index] = mesh_editor_capture_pre_edit_channels(
            found->second,
            state.normal_operation,
            state.normal_operation || state.operation == "brush"
                || (transform && bool_or(edit.get("recompute_normals"), true)),
            state.uv_operation,
            state.normal_operation || state.tangent_operation || state.uv_operation || transform,
            state.material_operation
        );
    }
}

void mesh_editor_initialize_apply_operation(
    const std::string& session_id,
    const std::string& native_session_id,
    MeshEditorSession& session,
    const JsonValue& edit,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    state.normal_operation = mesh_editor_is_normal_operation(state.operation);
    state.tangent_operation = mesh_editor_is_tangent_operation(state.operation);
    state.uv_operation = mesh_editor_is_uv_operation(state.operation);
    state.auto_uv_operation = state.uv_operation && bool_or(edit.get("auto_uv"), false);
    state.material_operation = state.operation == "material_assign" || state.operation == "material_copy";
    state.cleanup_operation = state.operation == "remove_doubles";
    state.delete_parts_operation = state.operation == "delete" && bool_or(edit.get("delete_parts"), false);
    state.record_history = bool_or(edit.get("record_history"), true);
    state.edit_root = mesh_editor_apply_root_json(
        session_id, native_session_id, session, edit, state.delta_output_dir
    );
    state.history.operation = state.operation;
    state.history.stroke_id = state.stroke_id;
    state.history.stroke_update_count = state.stroke_phase.empty() ? 0 : 1;
    mesh_editor_capture_apply_history(session, edit, native_session, state);
}
