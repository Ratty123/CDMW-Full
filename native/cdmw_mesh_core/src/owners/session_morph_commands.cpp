std::set<int> mesh_editor_morph_result_indices(const std::vector<SubmeshMeshEditResult>& results) {
    std::set<int> affected;
    for (const SubmeshMeshEditResult& result : results) {
        if (result.index >= 0 && !result.changed_vertices.empty()) affected.insert(result.index);
    }
    return affected;
}

std::map<int, MeshSessionSubmesh> mesh_editor_capture_morph_submeshes(
    const MeshEditorSession& session,
    const MeshMorphRuntime& next
) {
    const auto& submeshes = mesh_editor_submeshes(session);
    std::map<int, std::vector<Vec3>> next_layer = mesh_editor_build_procedural_morph_layer(next, submeshes);
    const std::set<int> indices = mesh_editor_morph_runtime_indices(*session.morph, next_layer);
    std::map<int, MeshSessionSubmesh> before;
    for (const int index : indices) {
        const auto found = submeshes.find(index);
        if (found != submeshes.end()) before[index] = found->second;
    }
    return before;
}

std::string mesh_editor_morph_state_session_report(
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    return mesh_editor_morph_report_json("morph_state", session_id, session, {}, {}, false, "", false, started);
}

std::string mesh_editor_morph_upload_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (session.morph && session.morph->unbaked) {
        throw std::runtime_error("Bake or Reset active procedural sliders before switching profiles");
    }
    auto next = mesh_editor_clone_morph_runtime(session);
    next->profile = mesh_editor_morph_profile_from_json(root.get("profile"), mesh_editor_submeshes(session));
    next->preset_id.clear();
    next->values.clear();
    next->current_layer.clear();
    if (next->profile) {
        for (const auto& item : next->profile->definitions) next->values[item.first] = 0.0;
    }
    next->unbaked = false;
    next->change_id.clear();
    next->active_change_id.clear();
    next->active_definition_id.clear();
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_upload";
    history.morph_before = session.morph;
    session.morph = std::move(next);
    const bool suppress_history = bool_or(root.get("suppress_history"), false);
    const bool history_published = suppress_history
        ? false
        : mesh_editor_publish_morph_history(session, std::move(history), {}, "", false);
    return mesh_editor_morph_report_json(
        "morph_upload", session_id, session, {}, {}, history_published, "", false, started
    );
}

bool mesh_editor_cancel_morph_change(
    MeshEditorSession& session,
    const std::string& change_id,
    const std::string& delta_output_dir,
    const std::string& session_id,
    std::vector<SubmeshMeshEditResult>& results
) {
    if (!session.morph || session.morph->active_change_id != change_id || session.undo_stack.empty()
        || session.undo_stack.back().stroke_id != change_id) {
        throw std::runtime_error("procedural morph cancel requires the matching active change");
    }
    MeshEditorHistoryEntry entry = std::move(session.undo_stack.back());
    session.undo_stack.pop_back();
    auto& submeshes = mesh_editor_submeshes(session);
    for (const auto& item : entry.deltas) {
        auto current = submeshes.find(item.first);
        if (current == submeshes.end()) throw std::runtime_error("procedural morph cancel topology changed");
        const std::vector<Vec3> before_positions = mesh_editor_history_current_positions(current->second, item.second);
        mesh_editor_apply_submesh_delta(current->second, item.second, true);
        results.push_back(mesh_editor_sparse_position_history_result(
            item.first, current->second, item.second, before_positions, "morph_cancel", delta_output_dir, session_id
        ));
    }
    session.morph = std::make_shared<MeshMorphRuntime>(entry.morph_before ? *entry.morph_before : MeshMorphRuntime{});
    session.morph->active_change_id.clear();
    session.morph->active_definition_id.clear();
    session.morph->active_change_update_count = 0;
    session.morph->state_revision = ++session.morph_state_revision;
    ++session.edit_revision;
    return true;
}

std::string mesh_editor_morph_change_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (!session.morph || !session.morph->profile) throw std::runtime_error("select a procedural morph profile first");
    const std::string definition_id = string_or(root.get("definition_id"), "");
    const auto definition = session.morph->profile->definitions.find(definition_id);
    if (definition == session.morph->profile->definitions.end()) throw std::runtime_error("unknown procedural morph definition");
    const std::string phase = lower_ascii(string_or(root.get("phase"), "end"));
    std::string change_id = string_or(root.get("change_id"), "");
    if (phase != "begin" && phase != "update" && phase != "end" && phase != "cancel") {
        throw std::runtime_error("unsupported procedural morph change phase");
    }
    if (change_id.empty()) throw std::runtime_error("procedural morph change requires change_id");
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    const bool include_edit_report = bool_or(root.get("include_edit_report"), !delta_output_dir.empty());
    std::vector<SubmeshMeshEditResult> results;
    bool history_published = false;
    if (phase == "cancel") {
        history_published = mesh_editor_cancel_morph_change(session, change_id, delta_output_dir, session_id, results);
        return mesh_editor_morph_report_json(
            "morph_change", session_id, session, results, mesh_editor_morph_result_indices(results), false,
            delta_output_dir, include_edit_report, started
        );
    }
    if (phase == "begin") {
        if (!session.morph->active_change_id.empty()) throw std::runtime_error("a procedural morph change is already active");
    } else if (phase == "update" || phase == "end") {
        if (session.morph->active_change_id.empty() && phase == "end") {
            // Keyboard/numeric commits may be a single final request.
        } else if (session.morph->active_change_id != change_id || session.morph->active_definition_id != definition_id) {
            throw std::runtime_error("procedural morph update requires the matching active change");
        }
    }
    auto next = mesh_editor_clone_morph_runtime(session);
    if (phase == "begin" || next->active_change_id.empty()) {
        next->active_change_id = change_id;
        next->active_definition_id = definition_id;
        next->active_change_update_count = 0;
    }
    const double raw_value = number_or(root.get("value"), definition->second.default_percent);
    next->values[definition_id] = std::max(definition->second.min_percent, std::min(definition->second.max_percent, raw_value));
    next->preset_id.clear();
    next->change_id = change_id;
    ++next->active_change_update_count;
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_change";
    history.morph_before = session.morph;
    std::map<int, MeshSessionSubmesh> before = mesh_editor_capture_morph_submeshes(session, *next);
    results = mesh_editor_recompose_morph(session, *next, "morph_change", delta_output_dir, session_id);
    if (phase == "end") {
        next->active_change_id.clear();
        next->active_definition_id.clear();
        next->active_change_update_count = 0;
    }
    session.morph = std::move(next);
    history_published = mesh_editor_publish_morph_history(session, std::move(history), before, change_id, phase != "begin");
    if (!results.empty()) ++session.edit_revision;
    return mesh_editor_morph_report_json(
        "morph_change", session_id, session, results, mesh_editor_morph_result_indices(results), history_published,
        delta_output_dir, include_edit_report, started
    );
}

std::string mesh_editor_morph_values_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (!session.morph || !session.morph->profile) throw std::runtime_error("select a procedural morph profile first");
    const JsonValue* raw_values = root.get("values");
    if (raw_values == nullptr || raw_values->type != JsonValue::Type::Object) throw std::runtime_error("morph preset requires values");
    auto next = mesh_editor_clone_morph_runtime(session);
    for (const auto& item : next->profile->definitions) {
        const JsonValue* value = raw_values->get(item.first);
        const double number = number_or(value, 0.0);
        next->values[item.first] = std::max(item.second.min_percent, std::min(item.second.max_percent, number));
    }
    next->preset_id = string_or(root.get("preset_id"), "preset");
    next->change_id = next->preset_id;
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_apply_preset";
    history.morph_before = session.morph;
    std::map<int, MeshSessionSubmesh> before = mesh_editor_capture_morph_submeshes(session, *next);
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    std::vector<SubmeshMeshEditResult> results = mesh_editor_recompose_morph(
        session, *next, "morph_apply_preset", delta_output_dir, session_id
    );
    session.morph = std::move(next);
    const bool history_published = mesh_editor_publish_morph_history(session, std::move(history), before, "", false);
    if (!results.empty()) ++session.edit_revision;
    return mesh_editor_morph_report_json(
        "morph_apply_preset", session_id, session, results, mesh_editor_morph_result_indices(results), history_published,
        delta_output_dir, bool_or(root.get("include_edit_report"), true), started
    );
}

std::set<int> mesh_editor_valid_submesh_set(
    const JsonValue* value,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::string& label
) {
    const std::vector<int> raw = int_vector_from_json(value);
    std::set<int> result;
    for (const int index : raw) {
        if (submeshes.find(index) == submeshes.end()) throw std::runtime_error(label + " contains a non-editable submesh");
        result.insert(index);
    }
    if (result.empty()) throw std::runtime_error(label + " requires at least one editable submesh");
    return result;
}

std::string mesh_editor_morph_set_driver_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    auto next = mesh_editor_clone_morph_runtime(session);
    next->driver_submesh_indices = mesh_editor_valid_submesh_set(
        root.get("submesh_indices"), mesh_editor_submeshes(session), "garment refit driver"
    );
    if (next->refit) throw std::runtime_error("Clear the active garment refit before changing its driver");
    next->change_id = "set-driver";
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_set_driver";
    history.morph_before = session.morph;
    session.morph = std::move(next);
    const bool history_published = mesh_editor_publish_morph_history(
        session, std::move(history), {}, "", false
    );
    return mesh_editor_morph_report_json(
        "morph_set_driver", session_id, session, {}, {}, history_published, "", false, started
    );
}

std::string mesh_editor_morph_bind_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (!session.morph || session.morph->driver_submesh_indices.empty()) throw std::runtime_error("Set Driver before binding a garment");
    const auto& submeshes = mesh_editor_submeshes(session);
    const std::set<int> garments = mesh_editor_valid_submesh_set(root.get("garment_submesh_indices"), submeshes, "garment refit target");
    auto next = mesh_editor_clone_morph_runtime(session);
    next->refit = mesh_editor_build_refit(submeshes, next->driver_submesh_indices, garments);
    next->change_id = "bind-refit";
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_bind";
    history.morph_before = session.morph;
    session.morph = std::move(next);
    const bool history_published = mesh_editor_publish_morph_history(session, std::move(history), {}, "", false);
    return mesh_editor_morph_report_json("morph_bind", session_id, session, {}, {}, history_published, "", false, started);
}

std::string mesh_editor_morph_configure_refit_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (!session.morph || !session.morph->refit) {
        throw std::runtime_error("Bind a garment before changing its refit settings");
    }
    const auto& submeshes = mesh_editor_submeshes(session);
    const std::set<int> garments = mesh_editor_valid_submesh_set(
        root.get("garment_submesh_indices"), submeshes, "garment refit settings"
    );
    for (const int index : garments) {
        if (session.morph->refit->garment_submesh_indices.find(index)
            == session.morph->refit->garment_submesh_indices.end()) {
            throw std::runtime_error("garment refit settings require a bound garment part");
        }
    }
    MeshRefitGarmentSettingsRuntime settings;
    settings.enabled = bool_or(root.get("enabled"), true);
    settings.intensity_percent = number_or(root.get("intensity_percent"), 100.0);
    settings.mode = lower_ascii(string_or(root.get("mode"), "surface"));
    settings.clearance_percent = number_or(root.get("clearance_percent"), 0.0);
    if (!std::isfinite(settings.intensity_percent)
        || settings.intensity_percent < 0.0 || settings.intensity_percent > 200.0) {
        throw std::runtime_error("garment refit intensity must be between 0 and 200 percent");
    }
    if (settings.mode != "surface" && settings.mode != "rigid") {
        throw std::runtime_error("garment refit mode must be surface or rigid");
    }
    if (!std::isfinite(settings.clearance_percent)
        || settings.clearance_percent < 0.0 || settings.clearance_percent > 5.0) {
        throw std::runtime_error("garment refit clearance must be between 0 and 5 percent of driver size");
    }
    auto next = mesh_editor_clone_morph_runtime(session);
    auto next_refit = std::make_shared<MeshRefitRuntime>(*next->refit);
    for (const int index : garments) next_refit->garment_settings[index] = settings;
    next->refit = std::move(next_refit);
    next->change_id = "configure-refit";
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_configure_refit";
    history.morph_before = session.morph;
    std::map<int, MeshSessionSubmesh> before = mesh_editor_capture_morph_submeshes(session, *next);
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    std::vector<SubmeshMeshEditResult> results = mesh_editor_recompose_morph(
        session, *next, "morph_configure_refit", delta_output_dir, session_id
    );
    session.morph = std::move(next);
    const bool history_published = mesh_editor_publish_morph_history(session, std::move(history), before, "", false);
    if (!results.empty()) ++session.edit_revision;
    return mesh_editor_morph_report_json(
        "morph_configure_refit", session_id, session, results, mesh_editor_morph_result_indices(results),
        history_published, delta_output_dir, bool_or(root.get("include_edit_report"), true), started
    );
}

std::shared_ptr<const MeshRefitRuntime> mesh_editor_rebased_refit(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    if (!morph.refit) return {};
    auto refit = std::make_shared<MeshRefitRuntime>(*morph.refit);
    for (const int driver_index : refit->driver_submesh_indices) {
        const auto found = submeshes.find(driver_index);
        if (found == submeshes.end()) throw std::runtime_error("garment refit driver topology changed");
        refit->driver_baseline_positions[driver_index] = found->second.vertices;
    }
    refit_rebind_bindings_native(*refit, submeshes);
    return refit;
}

std::string mesh_editor_morph_reset_or_bake_session_report(
    const std::string& command,
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    auto next = mesh_editor_clone_morph_runtime(session);
    MeshEditorHistoryEntry history;
    history.operation = command;
    history.morph_before = session.morph;
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    std::map<int, MeshSessionSubmesh> before;
    std::vector<SubmeshMeshEditResult> results;
    if (command == "morph_reset" || command == "morph_clear_refit") {
        if (command == "morph_reset") {
            for (auto& item : next->values) item.second = 0.0;
            next->preset_id.clear();
            const std::shared_ptr<const MeshRefitRuntime> retained_refit = next->refit;
            next->refit.reset();
            before = mesh_editor_capture_morph_submeshes(session, *next);
            results = mesh_editor_recompose_morph(session, *next, command, delta_output_dir, session_id);
            next->refit = retained_refit;
            next->refit = mesh_editor_rebased_refit(*next, mesh_editor_submeshes(session));
        } else {
            next->refit.reset();
            before = mesh_editor_capture_morph_submeshes(session, *next);
            results = mesh_editor_recompose_morph(session, *next, command, delta_output_dir, session_id);
        }
    } else {
        for (auto& item : next->values) item.second = 0.0;
        next->preset_id.clear();
        next->current_layer.clear();
        next->unbaked = false;
        next->refit = mesh_editor_rebased_refit(*next, mesh_editor_submeshes(session));
    }
    next->active_change_id.clear();
    next->active_definition_id.clear();
    next->active_change_update_count = 0;
    next->change_id = command;
    next->state_revision = ++session.morph_state_revision;
    session.morph = std::move(next);
    const bool suppress_history = bool_or(root.get("suppress_history"), false);
    const bool history_published = suppress_history
        ? false
        : mesh_editor_publish_morph_history(session, std::move(history), before, "", false);
    if (!results.empty()) ++session.edit_revision;
    return mesh_editor_morph_report_json(
        command, session_id, session, results, mesh_editor_morph_result_indices(results), history_published,
        delta_output_dir, bool_or(root.get("include_edit_report"), true), started
    );
}

bool mesh_editor_morph_topology_blocked(const MeshEditorSession& session) {
    return session.morph && session.morph->unbaked;
}

void mesh_editor_add_morph_history_candidates(
    const MeshEditorSession& session,
    std::set<int>& candidates
) {
    if (!session.morph || !session.morph->refit) return;
    candidates.insert(session.morph->refit->driver_submesh_indices.begin(), session.morph->refit->driver_submesh_indices.end());
    candidates.insert(session.morph->refit->garment_submesh_indices.begin(), session.morph->refit->garment_submesh_indices.end());
}

void mesh_editor_capture_morph_before_apply(MeshEditorSession& session, MeshEditorApplyState& state) {
    state.history.morph_before = session.morph;
}

void mesh_editor_append_refit_after_geometry(
    MeshEditorSession& session,
    MeshEditorApplyState& state
) {
    if (!session.morph || !session.morph->refit) return;
    bool position_change = false;
    for (const SubmeshMeshEditResult& result : state.results) {
        if (result.topology_changed) return;
        if (!result.changed_vertices.empty()) {
            position_change = true;
            break;
        }
    }
    if (!position_change) return;
    auto next = mesh_editor_clone_morph_runtime(session);
    std::vector<SubmeshMeshEditResult> refit_results = mesh_editor_recompose_morph(
        session, *next, "morph_refit", state.delta_output_dir, state.editor_session_id
    );
    if (!refit_results.empty()) {
        state.results.insert(
            state.results.end(),
            std::make_move_iterator(refit_results.begin()),
            std::make_move_iterator(refit_results.end())
        );
        next->state_revision = ++session.morph_state_revision;
        next->change_id = "geometry-refit";
        session.morph = std::move(next);
        state.history.morph_state_changed = true;
    }
}

void mesh_editor_finalize_morph_after_apply(MeshEditorSession& session, MeshEditorApplyState& state) {
    if (state.applied_topology_changed) {
        auto next = std::make_shared<MeshMorphRuntime>();
        next->state_revision = ++session.morph_state_revision;
        next->change_id = "topology-invalidated";
        session.morph = std::move(next);
        state.history.morph_state_changed = true;
    }
    if (state.history.morph_state_changed) state.history.morph_after = session.morph;
}
