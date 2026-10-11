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
    std::set<int> indices = mesh_editor_morph_runtime_indices(*session.morph, next_layer);
    for (const auto& item : mesh_editor_build_procedural_morph_layer(next, submeshes, true)) indices.insert(item.first);
    std::map<int, MeshSessionSubmesh> before;
    for (const int index : indices) {
        const auto found = submeshes.find(index);
        if (found != submeshes.end()) before[index] = found->second;
    }
    return before;
}

std::string mesh_editor_morph_state_session_report(
    const JsonValue& root,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    std::string report = mesh_editor_morph_report_json("morph_state", session_id, session, {}, {}, false, "", false, started);
    const bool include_neutral = bool_or(root.get("include_neutral_positions"), false);
    const bool include_masks = bool_or(root.get("include_effective_vertex_masks"), false);
    if (!include_neutral && !include_masks) return report;
    const auto& submeshes = mesh_editor_submeshes(session);
    const auto* requested = root.get("submesh_indices");
    if (!requested || requested->type != JsonValue::Type::Array || requested->array_value.empty()
        || requested->array_value.size() > submeshes.size()) {
        throw std::runtime_error("morph geometry query requires bounded explicit submesh indices");
    }
    std::set<int> indices;
    for (const auto& item : requested->array_value) {
        int index = -1;
        if (!strict_int_or(&item, index) || !submeshes.count(index) || !indices.insert(index).second)
            throw std::runtime_error("morph geometry query contains an invalid or duplicate submesh");
    }
    const MeshMorphRuntime empty;
    const auto& morph = session.morph ? *session.morph : empty;
    std::set<int> needed = indices;
    if (include_masks) {
        if (!morph.refit) throw std::runtime_error("effective influence query requires bound garments");
        for (const int index : indices) {
            if (!morph.refit->garment_submesh_indices.count(index))
                throw std::runtime_error("effective influence query references an unbound garment");
        }
        needed.insert(morph.refit->garment_submesh_indices.begin(), morph.refit->garment_submesh_indices.end());
    }
    const auto positions = mesh_editor_morph_residual_positions(morph, submeshes, needed);
    std::ostringstream out;
    out << report.substr(0, report.size() - 1);
    if (include_neutral) {
        out << ",\"neutral_positions\":[";
        bool wrote = false;
        for (const int index : indices) {
            if (wrote) out << ',';
            wrote = true;
            const auto& vertices = positions.at(index);
            out << "{\"submesh_index\":" << index << ",\"vertex_indices\":[";
            for (std::size_t i = 0; i < vertices.size(); ++i) { if (i) out << ','; out << i; }
            out << "],\"positions\":";
            mesh_editor_write_snapshot_vec3s(out, vertices);
            out << '}';
        }
        out << ']';
    }
    if (include_masks) {
        const auto masks = mesh_editor_refit_masks(*morph.refit, submeshes, positions);
        out << ",\"effective_vertex_masks\":[";
        bool wrote = false;
        for (const int index : indices) {
            if (wrote) out << ',';
            wrote = true;
            const std::size_t count = submeshes.at(index).vertices.size();
            const auto settings = morph.refit->garment_settings.find(index);
            const bool enabled = settings == morph.refit->garment_settings.end() || settings->second.enabled;
            out << "{\"submesh_index\":" << index << ",\"vertex_indices\":[";
            for (std::size_t vertex = 0; vertex < count; ++vertex) { if (vertex) out << ','; out << vertex; }
            out << "],\"weights\":[";
            for (std::size_t vertex = 0; vertex < count; ++vertex) {
                if (vertex) out << ',';
                out << std::setprecision(17) << (enabled ? mesh_editor_refit_mask_weight(masks, index, vertex) : 0.0);
            }
            out << "]}";
        }
        out << ']';
    }
    out << '}';
    return out.str();
}

std::string mesh_editor_morph_upload_preserving_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (session.morph && !session.morph->active_change_id.empty()) {
        throw std::runtime_error("Finish the active slider gesture before capturing an authored shape");
    }
    const bool preserve = bool_or(root.get("preserve_runtime"), false);
    if (session.morph && session.morph->unbaked && !preserve) {
        throw std::runtime_error("Bake or Reset active sliders before switching profiles");
    }
    auto& submeshes = mesh_editor_submeshes(session);
    const auto previous = session.morph;
    const MeshMorphRuntime empty;
    const auto& old = previous ? *previous : empty;
    auto next = mesh_editor_clone_morph_runtime(session);
    next->profile = mesh_editor_morph_profile_from_json(root.get("profile"), submeshes);
    next->values.clear();
    if (next->profile) for (const auto& item : next->profile->definitions) {
        const auto value = old.values.find(item.first);
        next->values[item.first] = preserve && value != old.values.end()
            ? std::clamp(value->second, item.second.min_percent, item.second.max_percent) : 0.0;
    }
    if (const auto* values = root.get("values")) {
        if (values->type != JsonValue::Type::Object) throw std::runtime_error("morph upload values must be an object");
        for (const auto& item : values->object_value) {
            if (!next->profile || !next->profile->definitions.count(item.first)
                || item.second.type != JsonValue::Type::Number || !std::isfinite(item.second.number_value)) {
                throw std::runtime_error("morph upload values reference an invalid slider");
            }
            const auto& definition = next->profile->definitions.at(item.first);
            if (item.second.number_value < definition.min_percent || item.second.number_value > definition.max_percent)
                throw std::runtime_error("morph upload value is outside its slider range");
            next->values[item.first] = item.second.number_value;
        }
    }
    std::set<int> indices;
    for (const auto& item : old.current_layer) indices.insert(item.first);
    if (next->profile) for (const auto& definition : next->profile->definitions) {
        for (const auto& item : definition.second.fields) indices.insert(item.first);
        for (const auto& item : definition.second.post_refit_fields) indices.insert(item.first);
    }
    if (next->refit) {
        indices.insert(next->refit->driver_submesh_indices.begin(), next->refit->driver_submesh_indices.end());
        indices.insert(next->refit->garment_submesh_indices.begin(), next->refit->garment_submesh_indices.end());
    }
    std::map<int, std::map<int, Vec3>> overrides;
    if (const auto* rows = root.get("neutral_positions")) {
        if (rows->type != JsonValue::Type::Array) throw std::runtime_error("neutral positions must be an array");
        for (const auto& row : rows->array_value) {
            int index = -1;
            if (row.type != JsonValue::Type::Object || !strict_int_or(row.get("submesh_index"), index)
                || !submeshes.count(index) || overrides.count(index)) {
                throw std::runtime_error("neutral positions reference an invalid or duplicate submesh");
            }
            const auto* vertices = row.get("vertex_indices");
            const auto* positions = row.get("positions");
            if (!vertices || !positions || vertices->type != JsonValue::Type::Array || positions->type != JsonValue::Type::Array
                || vertices->array_value.size() != positions->array_value.size()
                || vertices->array_value.size() > submeshes.at(index).vertices.size()) {
                throw std::runtime_error("neutral positions require matching bounded indices and positions");
            }
            auto& selected = overrides[index];
            for (std::size_t i = 0; i < vertices->array_value.size(); ++i) {
                int vertex = -1;
                const auto& position = positions->array_value[i];
                if (!strict_int_or(&vertices->array_value[i], vertex) || vertex < 0
                    || static_cast<std::size_t>(vertex) >= submeshes.at(index).vertices.size()
                    || position.type != JsonValue::Type::Array || position.array_value.size() != 3
                    || selected.count(vertex)) throw std::runtime_error("invalid neutral position vertex");
                Vec3 point{};
                for (int axis = 0; axis < 3; ++axis) {
                    const auto& value = position.array_value[axis];
                    if (value.type != JsonValue::Type::Number || !std::isfinite(value.number_value))
                        throw std::runtime_error("neutral position must be finite");
                    point[axis] = value.number_value;
                }
                selected.emplace(vertex, point);
            }
            indices.insert(index);
        }
    }
    auto residual = mesh_editor_morph_residual_positions(old, submeshes, indices);
    for (const auto& item : overrides) for (const auto& vertex : item.second)
        residual.at(item.first)[vertex.first] = vertex.second;
    std::map<int, MeshSessionSubmesh> before;
    for (const int index : indices) before[index] = submeshes.at(index);
    const auto old_state_revision = session.morph_state_revision;
    const auto old_edit_revision = session.edit_revision;
    const std::string output = string_or(root.get("delta_output_dir"), "");
    std::vector<SubmeshMeshEditResult> results;
    try {
        for (const auto& item : residual) submeshes.at(item.first).vertices = item.second;
        auto neutral = std::make_shared<MeshMorphRuntime>(old);
        neutral->current_layer.clear();
        for (const auto& item : residual) {
            neutral->neutral_positions[item.first] = item.second;
            neutral->composed_positions[item.first] = item.second;
        }
        // Retain affected zero layers so old-only profile and explicit base edits are recomposed.
        for (const int index : indices) neutral->current_layer[index] = mesh_editor_zero_morph_layer(submeshes.at(index).vertices.size());
        session.morph = neutral;
        next->current_layer.clear();
        next->active_change_id.clear();
        next->active_definition_id.clear();
        next->active_change_update_count = 0;
        next->preset_id.clear();
        mesh_editor_recompose_morph(session, *next, "morph_upload", output, session_id);
        // Report against the pre-transaction geometry, including neutral-only edits.
        for (const auto& item : before) {
            auto result = mesh_editor_morph_sparse_result(item.first, submeshes.at(item.first),
                item.second.vertices, "morph_upload", output, session_id);
            if (!result.changed_vertices.empty()) results.push_back(std::move(result));
        }
        next->change_id = "capture-authored";
        next->state_revision = ++session.morph_state_revision;
        session.morph = next;
    } catch (...) {
        for (auto& item : before) submeshes[item.first] = std::move(item.second);
        session.morph = previous;
        session.morph_state_revision = old_state_revision;
        session.edit_revision = old_edit_revision;
        throw;
    }
    MeshEditorHistoryEntry history;
    history.operation = "morph_upload";
    history.morph_before = previous;
    const bool published = bool_or(root.get("suppress_history"), false)
        ? false : mesh_editor_publish_morph_history(session, std::move(history), before, "", false);
    if (!results.empty()) ++session.edit_revision;
    return mesh_editor_morph_report_json("morph_upload", session_id, session, results,
        mesh_editor_morph_result_indices(results), published, output, bool_or(root.get("include_edit_report"), true), started);
}

std::string mesh_editor_morph_upload_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (bool_or(root.get("preserve_runtime"), false) || root.get("neutral_positions") || root.get("values")) {
        return mesh_editor_morph_upload_preserving_session_report(root, session_id, session, started);
    }
    if (session.morph && session.morph->unbaked) {
        throw std::runtime_error("Bake or Reset active procedural sliders before switching profiles");
    }
    auto next = mesh_editor_clone_morph_runtime(session);
    next->profile = mesh_editor_morph_profile_from_json(root.get("profile"), mesh_editor_submeshes(session));
    next->preset_id.clear();
    next->values.clear();
    next->current_layer.clear();
    next->neutral_positions.clear();
    next->composed_positions.clear();
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
    MeshEditorHistoryEntry history;
    history.operation = "morph_change";
    history.morph_before = session.morph;
    std::map<int, MeshSessionSubmesh> before = mesh_editor_capture_morph_submeshes(session, *next);
    results = mesh_editor_recompose_morph(session, *next, "morph_change", delta_output_dir, session_id);
    next->state_revision = ++session.morph_state_revision;
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
    MeshEditorHistoryEntry history;
    history.operation = "morph_apply_preset";
    history.morph_before = session.morph;
    std::map<int, MeshSessionSubmesh> before = mesh_editor_capture_morph_submeshes(session, *next);
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    std::vector<SubmeshMeshEditResult> results = mesh_editor_recompose_morph(
        session, *next, "morph_apply_preset", delta_output_dir, session_id
    );
    next->state_revision = ++session.morph_state_revision;
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

bool mesh_editor_refit_baseline_matches_publication(
    const std::vector<Vec3>& visible,
    const std::vector<Vec3>& baseline
) {
    if (visible.size() != baseline.size()) return false;
    for (std::size_t vertex = 0; vertex < visible.size(); ++vertex) {
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const double expected = baseline[vertex][axis];
            const double current = visible[vertex][axis];
            // Rust geometry publication may round coordinates to float32. Only
            // that exact representation change is allowed beside exact identity.
            if (current != expected && current != static_cast<double>(static_cast<float>(expected))) return false;
        }
    }
    return true;
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
    const auto regions = refit_regions_from_json_native(root.get("driver_regions"), submeshes, next->driver_submesh_indices);
    const bool preserve = bool_or(root.get("preserve_existing"), false);
    if (preserve && next->refit) {
        if (next->unbaked || !next->active_change_id.empty()) {
            throw std::runtime_error("Reset or Bake active deformation before changing a garment driver region");
        }
        for (const auto& item : next->refit->driver_baseline_positions) {
            if (!submeshes.count(item.first)
                || !mesh_editor_refit_baseline_matches_publication(submeshes.at(item.first).vertices, item.second)) {
                throw std::runtime_error("scoped refit binding requires the unchanged driver baseline");
            }
        }
    }
    auto rebound = std::make_shared<MeshRefitRuntime>(
        *mesh_editor_build_refit(submeshes, next->driver_submesh_indices, garments, regions));
    if (next->refit) {
        for (const int index : garments) {
            const auto settings = next->refit->garment_settings.find(index);
            if (settings != next->refit->garment_settings.end()) rebound->garment_settings[index] = settings->second;
            const auto mask = next->refit->vertex_masks.find(index);
            if (mask != next->refit->vertex_masks.end()) rebound->vertex_masks[index] = mask->second;
        }
        if (preserve) {
            for (const auto& binding : next->refit->bindings)
                if (!garments.count(binding.garment_submesh_index)) rebound->bindings.push_back(binding);
            for (const int index : next->refit->garment_submesh_indices) {
                if (garments.count(index)) continue;
                rebound->garment_submesh_indices.insert(index);
                rebound->garment_settings[index] = next->refit->garment_settings.at(index);
                const auto mask = next->refit->vertex_masks.find(index);
                if (mask != next->refit->vertex_masks.end()) rebound->vertex_masks[index] = mask->second;
                const auto old_region = next->refit->garment_regions.find(index);
                if (old_region != next->refit->garment_regions.end()) rebound->garment_regions[index] = old_region->second;
            }
            std::vector<double> distances;
            for (const auto& binding : rebound->bindings) distances.push_back(binding.distance);
            rebound->maximum_distance = *std::max_element(distances.begin(), distances.end());
            rebound->p95_distance = percentile_95_native(distances);
            rebound->distance_warning = rebound->maximum_distance > rebound->warning_distance
                || rebound->p95_distance > rebound->warning_distance;
            rebound->candidate_triangle_tests += next->refit->candidate_triangle_tests;
            rebound->driver_triangle_count = 0;
            for (const int index : rebound->driver_submesh_indices) for (const auto& face : submeshes.at(index).faces) {
                bool allowed = false;
                for (const int garment : rebound->garment_submesh_indices) {
                    const auto restriction = rebound->garment_regions.find(garment);
                    if (restriction == rebound->garment_regions.end()) { allowed = true; break; }
                    const auto region = restriction->second.find(index);
                    if (region != restriction->second.end() && region->second.count(face[0])
                        && region->second.count(face[1]) && region->second.count(face[2])) { allowed = true; break; }
                }
                if (allowed) ++rebound->driver_triangle_count;
            }
        }
    }
    next->refit = std::move(rebound);
    next->change_id = "bind-refit";
    next->state_revision = ++session.morph_state_revision;
    MeshEditorHistoryEntry history;
    history.operation = "morph_bind";
    history.morph_before = session.morph;
    session.morph = std::move(next);
    const bool history_published = mesh_editor_publish_morph_history(session, std::move(history), {}, "", false);
    return mesh_editor_morph_report_json("morph_bind", session_id, session, {}, {}, history_published, "", false, started);
}

MeshRefitGarmentSettingsRuntime mesh_editor_refit_settings_from_json(
    const JsonValue& raw,
    MeshRefitGarmentSettingsRuntime settings,
    bool strict_types
) {
    if (strict_types) {
        for (const auto* key : {"intensity_percent", "clearance_percent", "tightness_percent"}) {
            const auto* value = raw.get(key);
            if (value && value->type != JsonValue::Type::Number)
                throw std::runtime_error("garment refit settings require numeric intensity, clearance and tightness");
        }
        const auto* enabled = raw.get("enabled");
        const auto* mode = raw.get("mode");
        if ((enabled && enabled->type != JsonValue::Type::Bool)
            || (mode && mode->type != JsonValue::Type::String))
            throw std::runtime_error("garment refit settings require a boolean enabled value and string mode");
    }
    settings.enabled = bool_or(raw.get("enabled"), settings.enabled);
    settings.intensity_percent = number_or(raw.get("intensity_percent"), settings.intensity_percent);
    settings.mode = lower_ascii(string_or(raw.get("mode"), settings.mode));
    settings.clearance_percent = number_or(raw.get("clearance_percent"), settings.clearance_percent);
    settings.tightness_percent = number_or(raw.get("tightness_percent"), settings.tightness_percent);
    if (!std::isfinite(settings.tightness_percent)
        || settings.tightness_percent < 0.0 || settings.tightness_percent > 100.0) {
        throw std::runtime_error("garment refit tightness must be between 0 and 100 percent");
    }
    if (!std::isfinite(settings.intensity_percent)
        || settings.intensity_percent < 0.0 || settings.intensity_percent > 200.0) {
        throw std::runtime_error("garment refit intensity must be between 0 and 200 percent");
    }
    if (settings.mode != "surface" && settings.mode != "rigid" && settings.mode != "rigid_component") {
        throw std::runtime_error("garment refit mode must be surface, rigid or rigid_component");
    }
    if (!std::isfinite(settings.clearance_percent)
        || settings.clearance_percent < 0.0 || settings.clearance_percent > 5.0) {
        throw std::runtime_error("garment refit clearance must be between 0 and 5 percent of driver size");
    }
    return settings;
}

void mesh_editor_configure_refit_batch(
    const JsonValue& root,
    MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& garments
) {
    const auto* rows = root.get("garment_settings");
    const auto* selected = root.get("garment_submesh_indices");
    if (!rows || rows->type != JsonValue::Type::Array || rows->array_value.size() != garments.size()
        || !selected || selected->type != JsonValue::Type::Array || selected->array_value.size() != garments.size()) {
        throw std::runtime_error("garment refit settings rows must exactly cover the selected garments");
    }
    for (const auto& item : selected->array_value) {
        int index = -1;
        if (!strict_int_or(&item, index) || !garments.count(index))
            throw std::runtime_error("garment refit batch contains an invalid garment index");
    }
    for (const auto* key : {"enabled", "intensity_percent", "mode", "clearance_percent", "tightness_percent", "vertex_masks"}) {
        if (root.get(key)) throw std::runtime_error("garment refit batch cannot mix per-part and shared settings");
    }
    std::set<int> seen;
    for (const auto& row : rows->array_value) {
        int index = -1;
        if (row.type != JsonValue::Type::Object || !strict_int_or(row.get("submesh_index"), index)
            || !garments.count(index) || !seen.insert(index).second) {
            throw std::runtime_error("garment refit settings row references an invalid or duplicate garment");
        }
        const auto current = refit.garment_settings.find(index);
        const MeshRefitGarmentSettingsRuntime previous = current == refit.garment_settings.end()
            ? MeshRefitGarmentSettingsRuntime{} : current->second;
        refit.garment_settings[index] = mesh_editor_refit_settings_from_json(row, previous, true);
        const auto* mask = row.get("vertex_mask");
        if (!mask) continue;
        if (mask->type == JsonValue::Type::Null) {
            refit.vertex_masks.erase(index);
        } else {
            if (mask->type != JsonValue::Type::Object)
                throw std::runtime_error("garment refit batch vertex mask must be an object or null");
            JsonValue mask_row = *mask;
            mask_row.object_value["submesh_index"] = mesh_editor_json_number(index);
            JsonValue masks;
            masks.type = JsonValue::Type::Array;
            masks.array_value.push_back(std::move(mask_row));
            refit_read_vertex_masks_native(refit, &masks, submeshes, garments);
        }
    }
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
    auto next = mesh_editor_clone_morph_runtime(session);
    auto next_refit = std::make_shared<MeshRefitRuntime>(*next->refit);
    if (root.get("garment_settings")) {
        mesh_editor_configure_refit_batch(root, *next_refit, submeshes, garments);
    } else {
        for (const int index : garments) {
            MeshRefitGarmentSettingsRuntime defaults;
            // Older clients omit tightness. Preserve the authoritative per-Part value.
            defaults.tightness_percent = next_refit->garment_settings[index].tightness_percent;
            next_refit->garment_settings[index] = mesh_editor_refit_settings_from_json(root, defaults, true);
        }
        refit_read_vertex_masks_native(*next_refit, root.get("vertex_masks"), submeshes, garments);
    }
    next->refit = std::move(next_refit);
    next->change_id = "configure-refit";
    MeshEditorHistoryEntry history;
    history.operation = "morph_configure_refit";
    history.morph_before = session.morph;
    std::map<int, MeshSessionSubmesh> before = mesh_editor_capture_morph_submeshes(session, *next);
    const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
    std::vector<SubmeshMeshEditResult> results = mesh_editor_recompose_morph(
        session, *next, "morph_configure_refit", delta_output_dir, session_id
    );
    next->state_revision = ++session.morph_state_revision;
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
    for (auto& item : refit->garment_settings) item.second.tightness_percent = 0.0;
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
        next->neutral_positions.clear();
        next->composed_positions.clear();
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
