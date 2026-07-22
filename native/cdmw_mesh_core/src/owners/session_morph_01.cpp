std::shared_ptr<MeshMorphRuntime> mesh_editor_clone_morph_runtime(const MeshEditorSession& session) {
    return std::make_shared<MeshMorphRuntime>(session.morph ? *session.morph : MeshMorphRuntime{});
}

std::vector<Vec3> mesh_editor_zero_morph_layer(std::size_t count) {
    return std::vector<Vec3>(count, Vec3{0.0, 0.0, 0.0});
}

bool mesh_editor_morph_layer_has_value(const std::map<int, std::vector<Vec3>>& layer) {
    for (const auto& item : layer) {
        for (const Vec3& delta : item.second) {
            if (dot_vec3(delta, delta) > 1.0e-30) return true;
        }
    }
    return false;
}

void mesh_editor_validate_morph_profile_field(
    const std::map<int, MeshSessionSubmesh>& submeshes,
    int submesh_index,
    const MeshMorphSparseFieldRuntime& field
) {
    const auto found = submeshes.find(submesh_index);
    if (found == submeshes.end()) {
        throw std::runtime_error("procedural morph field references a missing editable submesh");
    }
    if (field.vertex_indices.empty() || field.vertex_indices.size() != field.deltas.size()) {
        throw std::runtime_error("procedural morph field requires matching sparse indices and deltas");
    }
    int previous = -1;
    for (std::size_t position = 0; position < field.vertex_indices.size(); ++position) {
        const int vertex_index = field.vertex_indices[position];
        const Vec3& delta = field.deltas[position];
        if (vertex_index <= previous || vertex_index < 0
            || static_cast<std::size_t>(vertex_index) >= found->second.vertices.size()) {
            throw std::runtime_error("procedural morph field contains an invalid or duplicate vertex index");
        }
        if (!std::isfinite(delta[0]) || !std::isfinite(delta[1]) || !std::isfinite(delta[2])) {
            throw std::runtime_error("procedural morph field contains a non-finite delta");
        }
        previous = vertex_index;
    }
}

std::shared_ptr<const MeshMorphProfileRuntime> mesh_editor_morph_profile_from_json(
    const JsonValue* raw_profile,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    if (raw_profile == nullptr || raw_profile->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing procedural morph profile");
    }
    const std::string profile_id = string_or(raw_profile->get("profile_id"), "");
    if (profile_id.empty()) {
        return {};
    }
    auto profile = std::make_shared<MeshMorphProfileRuntime>();
    profile->profile_id = profile_id;
    profile->name = string_or(raw_profile->get("name"), profile_id);
    profile->topology_fingerprint = string_or(raw_profile->get("topology_fingerprint"), "");
    if (profile->topology_fingerprint.size() != 64) {
        throw std::runtime_error("procedural morph profile is missing its exact topology fingerprint");
    }
    const JsonValue* raw_definitions = raw_profile->get("definitions");
    if (raw_definitions == nullptr || raw_definitions->type != JsonValue::Type::Array) {
        throw std::runtime_error("procedural morph profile is missing definitions");
    }
    for (const JsonValue& item : raw_definitions->array_value) {
        if (item.type != JsonValue::Type::Object) continue;
        MeshMorphDefinitionRuntime definition;
        definition.definition_id = string_or(item.get("definition_id"), "");
        definition.label = string_or(item.get("label"), definition.definition_id);
        definition.category = string_or(item.get("category"), "General");
        definition.min_percent = number_or(item.get("min_percent"), -100.0);
        definition.max_percent = number_or(item.get("max_percent"), 100.0);
        definition.default_percent = number_or(item.get("default_percent"), 0.0);
        if (definition.definition_id.empty() || !std::isfinite(definition.min_percent)
            || !std::isfinite(definition.max_percent) || !std::isfinite(definition.default_percent)
            || definition.min_percent >= definition.max_percent
            || definition.default_percent < definition.min_percent
            || definition.default_percent > definition.max_percent) {
            throw std::runtime_error("procedural morph definition metadata is invalid");
        }
        if (!profile->definitions.emplace(definition.definition_id, std::move(definition)).second) {
            throw std::runtime_error("procedural morph definition ids must be unique");
        }
    }
    const JsonValue* raw_fields = raw_profile->get("fields");
    if (raw_fields == nullptr || raw_fields->type != JsonValue::Type::Array) {
        throw std::runtime_error("procedural morph profile is missing sparse fields");
    }
    for (const JsonValue& item : raw_fields->array_value) {
        if (item.type != JsonValue::Type::Object) continue;
        const std::string definition_id = string_or(item.get("definition_id"), "");
        const int submesh_index = int_or(item.get("submesh_index"), -1);
        const auto definition = profile->definitions.find(definition_id);
        if (definition == profile->definitions.end() || submesh_index < 0) {
            throw std::runtime_error("procedural morph sparse field references an unknown definition or submesh");
        }
        MeshMorphSparseFieldRuntime field;
        field.vertex_indices = int_vector_from_json(item.get("vertex_indices"));
        field.deltas = vertices_from_json(item.get("deltas"));
        mesh_editor_validate_morph_profile_field(submeshes, submesh_index, field);
        if (!definition->second.fields.emplace(submesh_index, std::move(field)).second) {
            throw std::runtime_error("procedural morph definition contains duplicate submesh fields");
        }
    }
    for (const auto& definition : profile->definitions) {
        if (definition.second.fields.empty()) {
            throw std::runtime_error("procedural morph definition generated no sparse field");
        }
    }
    return profile;
}

std::map<int, std::vector<Vec3>> mesh_editor_build_procedural_morph_layer(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    std::map<int, std::vector<Vec3>> layer;
    if (!morph.profile) return layer;
    for (const auto& definition_item : morph.profile->definitions) {
        const MeshMorphDefinitionRuntime& definition = definition_item.second;
        const auto raw_value = morph.values.find(definition.definition_id);
        const double percent = std::max(
            definition.min_percent,
            std::min(definition.max_percent, raw_value == morph.values.end() ? 0.0 : raw_value->second)
        );
        if (std::fabs(percent) <= 1.0e-12) continue;
        const double factor = percent / 100.0;
        for (const auto& field_item : definition.fields) {
            const auto submesh = submeshes.find(field_item.first);
            if (submesh == submeshes.end()) {
                throw std::runtime_error("procedural morph profile topology is no longer available");
            }
            std::vector<Vec3>& deltas = layer[field_item.first];
            if (deltas.empty()) deltas = mesh_editor_zero_morph_layer(submesh->second.vertices.size());
            const MeshMorphSparseFieldRuntime& field = field_item.second;
            for (std::size_t position = 0; position < field.vertex_indices.size(); ++position) {
                const int vertex_index = field.vertex_indices[position];
                deltas[static_cast<std::size_t>(vertex_index)] = add_vec3(
                    deltas[static_cast<std::size_t>(vertex_index)],
                    scale_vec3(field.deltas[position], factor)
                );
            }
        }
    }
    return layer;
}

const std::vector<Vec3>& mesh_editor_morph_layer_for_submesh(
    const std::map<int, std::vector<Vec3>>& layer,
    int submesh_index,
    const std::vector<Vec3>& zero
) {
    const auto found = layer.find(submesh_index);
    return found == layer.end() ? zero : found->second;
}

Vec3 mesh_editor_refit_driver_point(
    const MeshRefitVertexBindingRuntime& binding,
    const std::map<int, std::vector<Vec3>>& positions
) {
    const auto found = positions.find(binding.driver_submesh_index);
    if (found == positions.end()) {
        throw std::runtime_error("garment refit driver positions are missing");
    }
    Vec3 point{0.0, 0.0, 0.0};
    for (std::size_t corner = 0; corner < 3; ++corner) {
        const int vertex_index = binding.driver_vertices[corner];
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= found->second.size()) {
            throw std::runtime_error("garment refit driver topology changed");
        }
        point = add_vec3(point, scale_vec3(found->second[static_cast<std::size_t>(vertex_index)], binding.barycentric[corner]));
    }
    return point;
}

void mesh_editor_add_refit_layer(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::vector<Vec3>>& residual,
    std::map<int, std::vector<Vec3>>& layer
) {
    if (!morph.refit) return;
    std::map<int, std::vector<Vec3>> driver_visible;
    for (const int driver_index : morph.refit->driver_submesh_indices) {
        const auto current = submeshes.find(driver_index);
        const auto residual_item = residual.find(driver_index);
        if (current == submeshes.end() || residual_item == residual.end()) {
            throw std::runtime_error("garment refit driver topology changed");
        }
        const std::vector<Vec3> zero = mesh_editor_zero_morph_layer(current->second.vertices.size());
        const std::vector<Vec3>& procedural = mesh_editor_morph_layer_for_submesh(layer, driver_index, zero);
        std::vector<Vec3>& visible = driver_visible[driver_index];
        visible.reserve(current->second.vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < current->second.vertices.size(); ++vertex_index) {
            visible.push_back(add_vec3(residual_item->second[vertex_index], procedural[vertex_index]));
        }
    }
    for (const MeshRefitVertexBindingRuntime& binding : morph.refit->bindings) {
        const auto target = submeshes.find(binding.garment_submesh_index);
        if (target == submeshes.end() || binding.garment_vertex_index < 0
            || static_cast<std::size_t>(binding.garment_vertex_index) >= target->second.vertices.size()) {
            throw std::runtime_error("garment refit target topology changed");
        }
        std::vector<Vec3>& target_layer = layer[binding.garment_submesh_index];
        if (target_layer.empty()) target_layer = mesh_editor_zero_morph_layer(target->second.vertices.size());
        const Vec3 current_point = mesh_editor_refit_driver_point(binding, driver_visible);
        const Vec3 baseline_point = mesh_editor_refit_driver_point(binding, morph.refit->driver_baseline_positions);
        target_layer[static_cast<std::size_t>(binding.garment_vertex_index)] = add_vec3(
            target_layer[static_cast<std::size_t>(binding.garment_vertex_index)],
            sub_vec3(current_point, baseline_point)
        );
    }
}

std::map<int, std::vector<Vec3>> mesh_editor_morph_residual_positions(
    const MeshMorphRuntime& morph,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& indices
) {
    std::map<int, std::vector<Vec3>> residual;
    for (const int index : indices) {
        const auto current = submeshes.find(index);
        if (current == submeshes.end()) continue;
        const std::vector<Vec3> zero = mesh_editor_zero_morph_layer(current->second.vertices.size());
        const std::vector<Vec3>& old_layer = mesh_editor_morph_layer_for_submesh(morph.current_layer, index, zero);
        if (old_layer.size() != current->second.vertices.size()) {
            throw std::runtime_error("procedural morph topology changed without Bake or Reset");
        }
        std::vector<Vec3>& values = residual[index];
        values.reserve(current->second.vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < current->second.vertices.size(); ++vertex_index) {
            values.push_back(sub_vec3(current->second.vertices[vertex_index], old_layer[vertex_index]));
        }
    }
    return residual;
}

std::set<int> mesh_editor_morph_runtime_indices(
    const MeshMorphRuntime& morph,
    const std::map<int, std::vector<Vec3>>& new_layer
) {
    std::set<int> indices;
    for (const auto& item : morph.current_layer) indices.insert(item.first);
    for (const auto& item : new_layer) indices.insert(item.first);
    if (morph.refit) {
        indices.insert(morph.refit->driver_submesh_indices.begin(), morph.refit->driver_submesh_indices.end());
        indices.insert(morph.refit->garment_submesh_indices.begin(), morph.refit->garment_submesh_indices.end());
    }
    return indices;
}

SubmeshMeshEditResult mesh_editor_morph_sparse_result(
    int submesh_index,
    MeshSessionSubmesh& submesh,
    const std::vector<Vec3>& before,
    const std::string& action,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshMeshEditResult result;
    result.index = submesh_index;
    result.action = action;
    result.sparse = true;
    result.resident_sparse = true;
    for (std::size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
        if (before[vertex_index] == submesh.vertices[vertex_index]) continue;
        result.changed_vertices.push_back(static_cast<int>(vertex_index));
        result.before_positions.push_back(before[vertex_index]);
        result.changed_positions.push_back(submesh.vertices[vertex_index]);
        result.changed_source_vertex_ids.push_back(
            submesh.source_vertex_map.size() == submesh.vertices.size()
                ? submesh.source_vertex_map[vertex_index]
                : static_cast<int>(vertex_index)
        );
    }
    if (!result.changed_vertices.empty()) {
        if (!submesh.faces.empty()) {
            submesh.normals = compute_smooth_normals(submesh.vertices, submesh.faces);
            result.preview_normals = submesh.normals;
        } else {
            submesh.normals.clear();
        }
        submesh.tangents.clear();
        submesh.tangent_signs.clear();
        mesh_editor_set_result_output_paths(result, delta_output_dir, session_id);
    }
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_recompose_morph(
    MeshEditorSession& session,
    MeshMorphRuntime& next,
    const std::string& action,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    std::map<int, MeshSessionSubmesh>& submeshes = mesh_editor_submeshes(session);
    std::map<int, std::vector<Vec3>> new_layer = mesh_editor_build_procedural_morph_layer(next, submeshes);
    std::set<int> indices = mesh_editor_morph_runtime_indices(*session.morph, new_layer);
    if (next.refit) {
        indices.insert(next.refit->driver_submesh_indices.begin(), next.refit->driver_submesh_indices.end());
        indices.insert(next.refit->garment_submesh_indices.begin(), next.refit->garment_submesh_indices.end());
    }
    const std::map<int, std::vector<Vec3>> residual = mesh_editor_morph_residual_positions(*session.morph, submeshes, indices);
    mesh_editor_add_refit_layer(next, submeshes, residual, new_layer);
    for (const auto& item : new_layer) indices.insert(item.first);
    std::vector<SubmeshMeshEditResult> results;
    for (const int index : indices) {
        auto current = submeshes.find(index);
        const auto residual_item = residual.find(index);
        if (current == submeshes.end() || residual_item == residual.end()) continue;
        const std::vector<Vec3> before = current->second.vertices;
        const std::vector<Vec3> zero = mesh_editor_zero_morph_layer(before.size());
        const std::vector<Vec3>& layer = mesh_editor_morph_layer_for_submesh(new_layer, index, zero);
        if (layer.size() != before.size()) throw std::runtime_error("procedural morph layer size mismatch");
        for (std::size_t vertex_index = 0; vertex_index < before.size(); ++vertex_index) {
            current->second.vertices[vertex_index] = add_vec3(residual_item->second[vertex_index], layer[vertex_index]);
        }
        SubmeshMeshEditResult result = mesh_editor_morph_sparse_result(
            index, current->second, before, action, delta_output_dir, session_id
        );
        if (!result.changed_vertices.empty()) results.push_back(std::move(result));
    }
    next.current_layer = std::move(new_layer);
    next.unbaked = mesh_editor_morph_layer_has_value(next.current_layer);
    return results;
}

MeshEditorSubmeshDelta mesh_editor_morph_history_delta(
    const MeshSessionSubmesh& before,
    const MeshSessionSubmesh& after
) {
    MeshEditorSubmeshDelta delta;
    delta.vertices = mesh_editor_make_channel_delta(before.vertices, after.vertices);
    delta.normals = mesh_editor_make_channel_delta(before.normals, after.normals);
    delta.tangents = mesh_editor_make_channel_delta(before.tangents, after.tangents);
    delta.tangent_signs = mesh_editor_make_channel_delta(before.tangent_signs, after.tangent_signs);
    return delta;
}

bool mesh_editor_publish_morph_history(
    MeshEditorSession& session,
    MeshEditorHistoryEntry entry,
    const std::map<int, MeshSessionSubmesh>& before,
    const std::string& change_id,
    bool coalesce
) {
    const auto& after = mesh_editor_submeshes(session);
    for (const auto& item : before) {
        const auto current = after.find(item.first);
        if (current == after.end()) continue;
        MeshEditorSubmeshDelta delta = mesh_editor_morph_history_delta(item.second, current->second);
        if (!mesh_editor_submesh_delta_empty(delta)) entry.deltas[item.first] = std::move(delta);
    }
    entry.morph_after = session.morph;
    entry.morph_state_changed = true;
    entry.stroke_id = change_id;
    if (coalesce && !change_id.empty() && !session.undo_stack.empty()) {
        MeshEditorHistoryEntry& previous = session.undo_stack.back();
        if (previous.operation == entry.operation && previous.stroke_id == change_id && !previous.topology_changed) {
            for (const auto& item : entry.deltas) {
                const auto found = previous.deltas.find(item.first);
                if (found != previous.deltas.end() && !mesh_editor_can_merge_submesh_delta(found->second, item.second)) {
                    throw std::runtime_error("procedural morph history could not coalesce its sparse delta");
                }
            }
            for (const auto& item : entry.deltas) {
                const auto found = previous.deltas.find(item.first);
                if (found == previous.deltas.end()) previous.deltas[item.first] = item.second;
                else (void)mesh_editor_merge_submesh_delta(found->second, item.second);
            }
            previous.morph_after = entry.morph_after;
            previous.stroke_update_count += 1;
            session.redo_stack.clear();
            mesh_editor_trim_session_history(session);
            return false;
        }
    }
    mesh_editor_push_history(session.undo_stack, std::move(entry));
    session.redo_stack.clear();
    mesh_editor_trim_session_history(session);
    return true;
}

void mesh_editor_write_morph_index_set(std::ostream& out, const std::set<int>& indices) {
    out << '[';
    bool wrote = false;
    for (const int index : indices) {
        if (wrote) out << ',';
        wrote = true;
        out << index;
    }
    out << ']';
}

void mesh_editor_write_morph_state(std::ostream& out, const MeshEditorSession& session) {
    const MeshMorphRuntime empty;
    const MeshMorphRuntime& morph = session.morph ? *session.morph : empty;
    out << "{\"profile_id\":";
    write_escaped(out, morph.profile ? morph.profile->profile_id : std::string());
    out << ",\"preset_id\":";
    write_escaped(out, morph.preset_id);
    out << ",\"values\":{";
    bool wrote = false;
    for (const auto& item : morph.values) {
        if (wrote) out << ',';
        wrote = true;
        write_escaped(out, item.first);
        out << ':' << std::setprecision(17) << item.second;
    }
    out << "},\"driver_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, morph.driver_submesh_indices);
    out << ",\"refit\":{";
    if (morph.refit) {
        out << "\"driver_submesh_indices\":";
        mesh_editor_write_morph_index_set(out, morph.refit->driver_submesh_indices);
        out << ",\"garment_submesh_indices\":";
        mesh_editor_write_morph_index_set(out, morph.refit->garment_submesh_indices);
        out << ",\"bound_vertex_count\":" << morph.refit->bindings.size()
            << ",\"maximum_distance\":" << std::setprecision(17) << morph.refit->maximum_distance
            << ",\"p95_distance\":" << morph.refit->p95_distance
            << ",\"warning_distance\":" << morph.refit->warning_distance
            << ",\"distance_warning\":" << (morph.refit->distance_warning ? "true" : "false");
    } else {
        out << "\"driver_submesh_indices\":[],\"garment_submesh_indices\":[],\"bound_vertex_count\":0,"
               "\"maximum_distance\":0,\"p95_distance\":0,\"warning_distance\":0,\"distance_warning\":false";
    }
    out << "},\"unbaked\":" << (morph.unbaked ? "true" : "false")
        << ",\"topology_blocked\":" << (morph.unbaked ? "true" : "false")
        << ",\"busy\":" << (!morph.active_change_id.empty() ? "true" : "false")
        << ",\"failure\":\"\",\"diagnostics\":[";
    if (morph.refit && morph.refit->distance_warning) {
        write_escaped(out, "Garment refit binding distances exceed the existing spatial warning threshold.");
    }
    out << "],\"state_revision\":" << morph.state_revision
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"change_id\":";
    write_escaped(out, morph.change_id);
    out << '}';
}

std::string mesh_editor_morph_report_json(
    const std::string& command,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::vector<SubmeshMeshEditResult>& results,
    const std::set<int>& affected,
    bool history_published,
    const std::string& delta_output_dir,
    bool include_edit_report,
    const std::chrono::steady_clock::time_point& started
) {
    const auto report_started = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
    const std::string edit_report = include_edit_report ? mesh_edit_report_json(results, true) : std::string();
    const auto finished = std::chrono::steady_clock::now();
    const double io_ms = std::chrono::duration<double, std::milli>(finished - report_started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":";
    write_escaped(out, command);
    out << ",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"affected_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, affected);
    out << ",\"topology_changed\":false,\"result_count\":" << results.size()
        << ",\"history_published\":" << (history_published ? "true" : "false")
        << ",\"change_id\":";
    write_escaped(out, session.morph ? session.morph->change_id : std::string());
    out << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    mesh_editor_write_submesh_summaries(out, session);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms, io_ms);
    if (include_edit_report) out << ",\"edit_report\":" << edit_report;
    out << ",\"morph_state\":";
    mesh_editor_write_morph_state(out, session);
    out << '}';
    (void)delta_output_dir;
    return out.str();
}

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
    session.morph = std::move(next);
    return mesh_editor_morph_report_json("morph_upload", session_id, session, {}, {}, false, "", false, started);
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
    session.morph = std::move(next);
    return mesh_editor_morph_report_json("morph_set_driver", session_id, session, {}, {}, false, "", false, started);
}

double mesh_editor_driver_diagonal(
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& drivers
) {
    bool initialized = false;
    Vec3 minimum{0.0, 0.0, 0.0};
    Vec3 maximum{0.0, 0.0, 0.0};
    for (const int index : drivers) {
        const auto found = submeshes.find(index);
        if (found == submeshes.end()) continue;
        for (const Vec3& vertex : found->second.vertices) {
            if (!initialized) {
                minimum = maximum = vertex;
                initialized = true;
            } else {
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    minimum[axis] = std::min(minimum[axis], vertex[axis]);
                    maximum[axis] = std::max(maximum[axis], vertex[axis]);
                }
            }
        }
    }
    return initialized ? length_vec3(sub_vec3(maximum, minimum)) : 0.0;
}

MeshRefitVertexBindingRuntime mesh_editor_closest_refit_binding(
    const Vec3& point,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& drivers
) {
    ClosestTrianglePointNative closest;
    MeshRefitVertexBindingRuntime binding;
    for (const int driver_index : drivers) {
        const auto found = submeshes.find(driver_index);
        if (found == submeshes.end()) continue;
        for (const auto& face : found->second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= found->second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= found->second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= found->second.vertices.size()) continue;
            const ClosestTrianglePointNative candidate = closest_triangle_point_native(
                point,
                found->second.vertices[static_cast<std::size_t>(face[0])],
                found->second.vertices[static_cast<std::size_t>(face[1])],
                found->second.vertices[static_cast<std::size_t>(face[2])]
            );
            if (candidate.distance_squared < closest.distance_squared) {
                closest = candidate;
                binding.driver_submesh_index = driver_index;
                binding.driver_vertices = face;
                binding.barycentric = candidate.barycentric;
            }
        }
    }
    if (binding.driver_submesh_index < 0 || !std::isfinite(closest.distance_squared)) {
        throw std::runtime_error("garment refit could not bind every vertex to a driver triangle");
    }
    binding.distance = std::sqrt(std::max(0.0, closest.distance_squared));
    return binding;
}

std::tuple<long long, long long, long long> mesh_editor_refit_cell(const Vec3& point, double tolerance) {
    return {
        static_cast<long long>(std::floor(point[0] / tolerance)),
        static_cast<long long>(std::floor(point[1] / tolerance)),
        static_cast<long long>(std::floor(point[2] / tolerance)),
    };
}

std::shared_ptr<const MeshRefitRuntime> mesh_editor_build_refit(
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& drivers,
    const std::set<int>& garments
) {
    for (const int index : garments) {
        if (drivers.find(index) != drivers.end()) throw std::runtime_error("garment refit driver and garment selections must not overlap");
    }
    auto refit = std::make_shared<MeshRefitRuntime>();
    refit->driver_submesh_indices = drivers;
    refit->garment_submesh_indices = garments;
    std::vector<Vec3> all_driver_vertices;
    for (const int driver_index : drivers) {
        const auto found = submeshes.find(driver_index);
        if (found == submeshes.end() || found->second.faces.empty()) {
            throw std::runtime_error("garment refit drivers require editable triangles");
        }
        refit->driver_baseline_positions[driver_index] = found->second.vertices;
        all_driver_vertices.insert(all_driver_vertices.end(), found->second.vertices.begin(), found->second.vertices.end());
    }
    const double diagonal = mesh_editor_driver_diagonal(submeshes, drivers);
    const double cohort_tolerance = std::max(1.0e-6, diagonal * 1.0e-7);
    refit->warning_distance = skin_transfer_distance_limit_native(all_driver_vertices);
    std::map<std::tuple<long long, long long, long long>, std::vector<std::pair<Vec3, MeshRefitVertexBindingRuntime>>> cohorts;
    std::vector<double> distances;
    for (const int garment_index : garments) {
        const auto garment = submeshes.find(garment_index);
        if (garment == submeshes.end()) throw std::runtime_error("garment refit target is not editable");
        for (std::size_t vertex_index = 0; vertex_index < garment->second.vertices.size(); ++vertex_index) {
            const Vec3 point = garment->second.vertices[vertex_index];
            const auto cell = mesh_editor_refit_cell(point, cohort_tolerance);
            MeshRefitVertexBindingRuntime binding;
            bool reused = false;
            for (long long dx = -1; dx <= 1 && !reused; ++dx) {
                for (long long dy = -1; dy <= 1 && !reused; ++dy) {
                    for (long long dz = -1; dz <= 1 && !reused; ++dz) {
                        const auto found = cohorts.find({std::get<0>(cell) + dx, std::get<1>(cell) + dy, std::get<2>(cell) + dz});
                        if (found == cohorts.end()) continue;
                        for (const auto& candidate : found->second) {
                            if (distance_squared_vec3(point, candidate.first) <= cohort_tolerance * cohort_tolerance) {
                                binding = candidate.second;
                                reused = true;
                                break;
                            }
                        }
                    }
                }
            }
            if (!reused) {
                binding = mesh_editor_closest_refit_binding(point, submeshes, drivers);
                cohorts[cell].push_back({point, binding});
            }
            const Vec3 bound_point = mesh_editor_refit_driver_point(
                binding,
                refit->driver_baseline_positions
            );
            binding.distance = length_vec3(sub_vec3(point, bound_point));
            binding.garment_submesh_index = garment_index;
            binding.garment_vertex_index = static_cast<int>(vertex_index);
            distances.push_back(binding.distance);
            refit->bindings.push_back(std::move(binding));
        }
    }
    if (refit->bindings.empty()) throw std::runtime_error("garment refit target selection contains no vertices");
    refit->maximum_distance = *std::max_element(distances.begin(), distances.end());
    refit->p95_distance = percentile_95_native(distances);
    refit->distance_warning = refit->maximum_distance > refit->warning_distance || refit->p95_distance > refit->warning_distance;
    return refit;
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
