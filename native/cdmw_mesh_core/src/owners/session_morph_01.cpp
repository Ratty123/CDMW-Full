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
        MeshRefitGarmentSettingsRuntime settings;
        const auto configured = morph.refit->garment_settings.find(binding.garment_submesh_index);
        if (configured != morph.refit->garment_settings.end()) settings = configured->second;
        if (!settings.enabled) continue;
        const auto target = submeshes.find(binding.garment_submesh_index);
        const auto target_residual = residual.find(binding.garment_submesh_index);
        if (target == submeshes.end() || target_residual == residual.end() || binding.garment_vertex_index < 0
            || static_cast<std::size_t>(binding.garment_vertex_index) >= target->second.vertices.size()) {
            throw std::runtime_error("garment refit target topology changed");
        }
        std::vector<Vec3>& target_layer = layer[binding.garment_submesh_index];
        if (target_layer.empty()) target_layer = mesh_editor_zero_morph_layer(target->second.vertices.size());
        const std::size_t target_vertex_index = static_cast<std::size_t>(binding.garment_vertex_index);
        const Vec3 current_point = mesh_editor_refit_driver_point(binding, driver_visible);
        const Vec3 baseline_point = mesh_editor_refit_driver_point(binding, morph.refit->driver_baseline_positions);
        Vec3 refit_delta = add_vec3(
            sub_vec3(current_point, baseline_point),
            refit_normal_correction_native(binding, driver_visible)
        );
        if (settings.mode == "rigid") {
            Vec3 rigid_delta{0.0, 0.0, 0.0};
            if (refit_rigid_delta_native(
                    binding, morph.refit->driver_baseline_positions, driver_visible, rigid_delta
                )) refit_delta = rigid_delta;
        }
        const double intensity = settings.intensity_percent / 100.0;
        if (intensity != 1.0) refit_delta = scale_vec3(refit_delta, intensity);
        const double clearance = morph.refit->driver_diagonal * settings.clearance_percent / 100.0;
        if (clearance > 0.0) {
            Vec3 outward = refit_binding_face_normal_native(binding, driver_visible);
            if (binding.normal_height < 0.0) outward = scale_vec3(outward, -1.0);
            if (dot_vec3(outward, outward) > 0.0) {
                const Vec3 predicted = add_vec3(
                    add_vec3(target_residual->second[target_vertex_index], target_layer[target_vertex_index]),
                    refit_delta
                );
                const double signed_clearance = dot_vec3(sub_vec3(predicted, current_point), outward);
                if (signed_clearance < clearance) {
                    refit_delta = add_vec3(refit_delta, scale_vec3(outward, clearance - signed_clearance));
                }
            }
        }
        target_layer[target_vertex_index] = add_vec3(target_layer[target_vertex_index], refit_delta);
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

void mesh_editor_write_refit_settings(std::ostream& out, const MeshRefitRuntime& refit) {
    out << '[';
    bool wrote = false;
    for (const int submesh_index : refit.garment_submesh_indices) {
        MeshRefitGarmentSettingsRuntime settings;
        const auto found = refit.garment_settings.find(submesh_index);
        if (found != refit.garment_settings.end()) settings = found->second;
        if (wrote) out << ',';
        wrote = true;
        out << "{\"submesh_index\":" << submesh_index
            << ",\"enabled\":" << (settings.enabled ? "true" : "false")
            << ",\"intensity_percent\":" << std::setprecision(17) << settings.intensity_percent
            << ",\"mode\":";
        write_escaped(out, settings.mode);
        out << ",\"clearance_percent\":" << std::setprecision(17) << settings.clearance_percent << '}';
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
            << ",\"distance_warning\":" << (morph.refit->distance_warning ? "true" : "false")
            << ",\"driver_triangle_count\":" << morph.refit->driver_triangle_count
            << ",\"candidate_triangle_tests\":" << morph.refit->candidate_triangle_tests
            << ",\"garment_settings\":";
        mesh_editor_write_refit_settings(out, *morph.refit);
    } else {
        out << "\"driver_submesh_indices\":[],\"garment_submesh_indices\":[],\"bound_vertex_count\":0,"
               "\"maximum_distance\":0,\"p95_distance\":0,\"warning_distance\":0,\"distance_warning\":false,"
               "\"driver_triangle_count\":0,\"candidate_triangle_tests\":0,\"garment_settings\":[]";
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

constexpr const char* MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA =
    "cdmw_mesh_editor_morph_runtime_snapshot_v1";
constexpr std::size_t MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_MAX_BYTES =
    256ULL * 1024ULL * 1024ULL;

std::uint32_t mesh_editor_snapshot_rotr(std::uint32_t value, int count) {
    return (value >> count) | (value << (32 - count));
}

std::string mesh_editor_snapshot_sha256(const std::string& payload) {
    static constexpr std::array<std::uint32_t, 64> constants{
        0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
        0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
        0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
        0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
        0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
        0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
        0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
        0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
        0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
        0xc67178f2U,
    };
    std::array<std::uint32_t, 8> digest{
        0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
        0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
    };
    if (payload.size() > (std::numeric_limits<std::uint64_t>::max() / 8ULL)) {
        throw std::runtime_error("morph runtime snapshot payload is too large to hash");
    }
    const std::uint64_t bit_length = static_cast<std::uint64_t>(payload.size()) * 8ULL;
    const std::size_t padded_size = ((payload.size() + 9ULL + 63ULL) / 64ULL) * 64ULL;
    for (std::size_t block_start = 0; block_start < padded_size; block_start += 64ULL) {
        std::array<std::uint32_t, 64> words{};
        for (std::size_t word_index = 0; word_index < 16; ++word_index) {
            std::uint32_t word = 0;
            for (std::size_t byte_index = 0; byte_index < 4; ++byte_index) {
                const std::size_t offset = block_start + word_index * 4ULL + byte_index;
                unsigned char value = 0;
                if (offset < payload.size()) {
                    value = static_cast<unsigned char>(payload[offset]);
                } else if (offset == payload.size()) {
                    value = 0x80U;
                } else if (offset >= padded_size - 8ULL) {
                    const std::size_t shift = (padded_size - 1ULL - offset) * 8ULL;
                    value = static_cast<unsigned char>((bit_length >> shift) & 0xffU);
                }
                word = (word << 8U) | static_cast<std::uint32_t>(value);
            }
            words[word_index] = word;
        }
        for (std::size_t index = 16; index < words.size(); ++index) {
            const std::uint32_t s0 = mesh_editor_snapshot_rotr(words[index - 15], 7)
                ^ mesh_editor_snapshot_rotr(words[index - 15], 18)
                ^ (words[index - 15] >> 3U);
            const std::uint32_t s1 = mesh_editor_snapshot_rotr(words[index - 2], 17)
                ^ mesh_editor_snapshot_rotr(words[index - 2], 19)
                ^ (words[index - 2] >> 10U);
            words[index] = words[index - 16] + s0 + words[index - 7] + s1;
        }
        std::uint32_t a = digest[0];
        std::uint32_t b = digest[1];
        std::uint32_t c = digest[2];
        std::uint32_t d = digest[3];
        std::uint32_t e = digest[4];
        std::uint32_t f = digest[5];
        std::uint32_t g = digest[6];
        std::uint32_t h = digest[7];
        for (std::size_t index = 0; index < words.size(); ++index) {
            const std::uint32_t sum1 = mesh_editor_snapshot_rotr(e, 6)
                ^ mesh_editor_snapshot_rotr(e, 11)
                ^ mesh_editor_snapshot_rotr(e, 25);
            const std::uint32_t choose = (e & f) ^ ((~e) & g);
            const std::uint32_t temp1 = h + sum1 + choose + constants[index] + words[index];
            const std::uint32_t sum0 = mesh_editor_snapshot_rotr(a, 2)
                ^ mesh_editor_snapshot_rotr(a, 13)
                ^ mesh_editor_snapshot_rotr(a, 22);
            const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
            const std::uint32_t temp2 = sum0 + majority;
            h = g;
            g = f;
            f = e;
            e = d + temp1;
            d = c;
            c = b;
            b = a;
            a = temp1 + temp2;
        }
        digest[0] += a;
        digest[1] += b;
        digest[2] += c;
        digest[3] += d;
        digest[4] += e;
        digest[5] += f;
        digest[6] += g;
        digest[7] += h;
    }
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (const std::uint32_t value : digest) out << std::setw(8) << value;
    return out.str();
}

std::string mesh_editor_morph_topology_digest(const MeshEditorSession& session) {
    std::ostringstream out;
    out << '[';
    bool wrote_submesh = false;
    for (const auto& item : mesh_editor_submeshes(session)) {
        if (wrote_submesh) out << ',';
        wrote_submesh = true;
        out << "{\"faces\":[";
        bool wrote_face = false;
        for (const auto& face : item.second.faces) {
            if (wrote_face) out << ',';
            wrote_face = true;
            out << '[' << face[0] << ',' << face[1] << ',' << face[2] << ']';
        }
        out << "],\"index\":" << item.first
            << ",\"vertex_count\":" << item.second.vertices.size() << '}';
    }
    out << ']';
    return mesh_editor_snapshot_sha256(out.str());
}

void mesh_editor_write_snapshot_vec3(std::ostream& out, const Vec3& value) {
    out << '[' << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2] << ']';
}

void mesh_editor_write_snapshot_vec3s(std::ostream& out, const std::vector<Vec3>& values) {
    out << '[';
    bool wrote = false;
    for (const Vec3& value : values) {
        if (wrote) out << ',';
        wrote = true;
        mesh_editor_write_snapshot_vec3(out, value);
    }
    out << ']';
}

void mesh_editor_write_snapshot_profile(std::ostream& out, const MeshMorphRuntime& morph) {
    if (!morph.profile) {
        out << "null";
        return;
    }
    out << "{\"profile_id\":";
    write_escaped(out, morph.profile->profile_id);
    out << ",\"name\":";
    write_escaped(out, morph.profile->name);
    out << ",\"topology_fingerprint\":";
    write_escaped(out, morph.profile->topology_fingerprint);
    out << ",\"definitions\":[";
    bool wrote_definition = false;
    for (const auto& item : morph.profile->definitions) {
        if (wrote_definition) out << ',';
        wrote_definition = true;
        const MeshMorphDefinitionRuntime& definition = item.second;
        out << "{\"definition_id\":";
        write_escaped(out, definition.definition_id);
        out << ",\"label\":";
        write_escaped(out, definition.label);
        out << ",\"category\":";
        write_escaped(out, definition.category);
        out << ",\"min_percent\":" << std::setprecision(17) << definition.min_percent
            << ",\"max_percent\":" << definition.max_percent
            << ",\"default_percent\":" << definition.default_percent << '}';
    }
    out << "],\"fields\":[";
    bool wrote_field = false;
    for (const auto& definition_item : morph.profile->definitions) {
        for (const auto& field_item : definition_item.second.fields) {
            if (wrote_field) out << ',';
            wrote_field = true;
            out << "{\"definition_id\":";
            write_escaped(out, definition_item.first);
            out << ",\"submesh_index\":" << field_item.first << ",\"vertex_indices\":[";
            bool wrote_index = false;
            for (const int vertex_index : field_item.second.vertex_indices) {
                if (wrote_index) out << ',';
                wrote_index = true;
                out << vertex_index;
            }
            out << "],\"deltas\":";
            mesh_editor_write_snapshot_vec3s(out, field_item.second.deltas);
            out << '}';
        }
    }
    out << "]}";
}

void mesh_editor_write_snapshot_refit(std::ostream& out, const MeshMorphRuntime& morph) {
    if (!morph.refit) {
        out << "null";
        return;
    }
    const MeshRefitRuntime& refit = *morph.refit;
    out << "{\"driver_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, refit.driver_submesh_indices);
    out << ",\"garment_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, refit.garment_submesh_indices);
    out << ",\"driver_baseline_positions\":[";
    bool wrote_baseline = false;
    for (const auto& item : refit.driver_baseline_positions) {
        if (wrote_baseline) out << ',';
        wrote_baseline = true;
        out << "{\"submesh_index\":" << item.first << ",\"positions\":";
        mesh_editor_write_snapshot_vec3s(out, item.second);
        out << '}';
    }
    out << "],\"bindings\":[";
    bool wrote_binding = false;
    for (const MeshRefitVertexBindingRuntime& binding : refit.bindings) {
        if (wrote_binding) out << ',';
        wrote_binding = true;
        out << "{\"garment_submesh_index\":" << binding.garment_submesh_index
            << ",\"garment_vertex_index\":" << binding.garment_vertex_index
            << ",\"driver_submesh_index\":" << binding.driver_submesh_index
            << ",\"driver_vertices\":[" << binding.driver_vertices[0] << ','
            << binding.driver_vertices[1] << ',' << binding.driver_vertices[2]
            << "],\"barycentric\":[" << std::setprecision(17) << binding.barycentric[0] << ','
            << binding.barycentric[1] << ',' << binding.barycentric[2]
            << "],\"distance\":" << binding.distance << ",\"baseline_normal\":";
        mesh_editor_write_snapshot_vec3(out, binding.baseline_normal);
        out << ",\"normal_height\":" << binding.normal_height << ",\"rigid_local_offset\":";
        mesh_editor_write_snapshot_vec3(out, binding.rigid_local_offset);
        out << ",\"rigid_frame_valid\":" << (binding.rigid_frame_valid ? "true" : "false") << '}';
    }
    out << "],\"garment_settings\":[";
    bool wrote_settings = false;
    for (const auto& item : refit.garment_settings) {
        if (wrote_settings) out << ',';
        wrote_settings = true;
        out << "{\"submesh_index\":" << item.first
            << ",\"enabled\":" << (item.second.enabled ? "true" : "false")
            << ",\"intensity_percent\":" << std::setprecision(17) << item.second.intensity_percent
            << ",\"mode\":";
        write_escaped(out, item.second.mode);
        out << ",\"clearance_percent\":" << item.second.clearance_percent << '}';
    }
    out << "],\"driver_diagonal\":" << std::setprecision(17) << refit.driver_diagonal
        << ",\"maximum_distance\":" << refit.maximum_distance
        << ",\"p95_distance\":" << refit.p95_distance
        << ",\"warning_distance\":" << refit.warning_distance
        << ",\"distance_warning\":" << (refit.distance_warning ? "true" : "false")
        << ",\"driver_triangle_count\":" << refit.driver_triangle_count
        << ",\"candidate_triangle_tests\":" << refit.candidate_triangle_tests << '}';
}

std::string mesh_editor_morph_runtime_snapshot_payload(const MeshEditorSession& session) {
    const MeshMorphRuntime empty;
    const MeshMorphRuntime& morph = session.morph ? *session.morph : empty;
    std::ostringstream out;
    out << "{\"profile\":";
    mesh_editor_write_snapshot_profile(out, morph);
    out << ",\"preset_id\":";
    write_escaped(out, morph.preset_id);
    out << ",\"values\":{";
    bool wrote_value = false;
    for (const auto& item : morph.values) {
        if (wrote_value) out << ',';
        wrote_value = true;
        write_escaped(out, item.first);
        out << ':' << std::setprecision(17) << item.second;
    }
    out << "},\"current_layer\":[";
    bool wrote_layer = false;
    for (const auto& item : morph.current_layer) {
        if (wrote_layer) out << ',';
        wrote_layer = true;
        out << "{\"submesh_index\":" << item.first << ",\"deltas\":";
        mesh_editor_write_snapshot_vec3s(out, item.second);
        out << '}';
    }
    out << "],\"driver_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, morph.driver_submesh_indices);
    out << ",\"refit\":";
    mesh_editor_write_snapshot_refit(out, morph);
    out << ",\"unbaked\":" << (morph.unbaked ? "true" : "false")
        << ",\"state_revision\":" << morph.state_revision
        << ",\"change_id\":";
    write_escaped(out, morph.change_id);
    out << ",\"active_change_id\":";
    write_escaped(out, morph.active_change_id);
    out << ",\"active_definition_id\":";
    write_escaped(out, morph.active_definition_id);
    out << ",\"active_change_update_count\":" << morph.active_change_update_count << '}';
    return out.str();
}

const JsonValue& mesh_editor_snapshot_required_member(
    const JsonValue& object,
    const std::string& key,
    JsonValue::Type type
) {
    const JsonValue* value = object.get(key);
    if (value == nullptr || value->type != type) {
        throw std::runtime_error("morph runtime snapshot has invalid " + key);
    }
    return *value;
}

double mesh_editor_snapshot_number(const JsonValue& object, const std::string& key) {
    const JsonValue& value = mesh_editor_snapshot_required_member(object, key, JsonValue::Type::Number);
    if (!std::isfinite(value.number_value)) {
        throw std::runtime_error("morph runtime snapshot has non-finite " + key);
    }
    return value.number_value;
}

long long mesh_editor_snapshot_integer(
    const JsonValue& object,
    const std::string& key,
    long long minimum = 0
) {
    const double value = mesh_editor_snapshot_number(object, key);
    constexpr double exact_integer_limit = 9007199254740991.0;
    if (std::floor(value) != value || value < static_cast<double>(minimum) || value > exact_integer_limit) {
        throw std::runtime_error("morph runtime snapshot has invalid integer " + key);
    }
    return static_cast<long long>(value);
}

bool mesh_editor_snapshot_bool(const JsonValue& object, const std::string& key) {
    return mesh_editor_snapshot_required_member(object, key, JsonValue::Type::Bool).bool_value;
}

std::string mesh_editor_snapshot_string(const JsonValue& object, const std::string& key) {
    return mesh_editor_snapshot_required_member(object, key, JsonValue::Type::String).string_value;
}

Vec3 mesh_editor_snapshot_vec3(const JsonValue& value, const std::string& label) {
    if (value.type != JsonValue::Type::Array || value.array_value.size() != 3) {
        throw std::runtime_error("morph runtime snapshot has invalid " + label);
    }
    Vec3 result{};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (value.array_value[axis].type != JsonValue::Type::Number
            || !std::isfinite(value.array_value[axis].number_value)) {
            throw std::runtime_error("morph runtime snapshot has non-finite " + label);
        }
        result[axis] = value.array_value[axis].number_value;
    }
    return result;
}

std::vector<Vec3> mesh_editor_snapshot_vec3s(const JsonValue& value, const std::string& label) {
    if (value.type != JsonValue::Type::Array) {
        throw std::runtime_error("morph runtime snapshot has invalid " + label);
    }
    std::vector<Vec3> result;
    result.reserve(value.array_value.size());
    for (const JsonValue& item : value.array_value) {
        result.push_back(mesh_editor_snapshot_vec3(item, label));
    }
    return result;
}

std::set<int> mesh_editor_snapshot_submesh_set(
    const JsonValue& value,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::string& label,
    bool allow_empty
) {
    if (value.type != JsonValue::Type::Array) {
        throw std::runtime_error("morph runtime snapshot has invalid " + label);
    }
    std::set<int> result;
    for (const JsonValue& item : value.array_value) {
        int index = -1;
        if (!strict_int_or(&item, index) || index < 0 || submeshes.find(index) == submeshes.end()
            || !result.insert(index).second) {
            throw std::runtime_error("morph runtime snapshot has invalid " + label);
        }
    }
    if (!allow_empty && result.empty()) {
        throw std::runtime_error("morph runtime snapshot has empty " + label);
    }
    return result;
}

std::shared_ptr<const MeshRefitRuntime> mesh_editor_refit_from_snapshot(
    const JsonValue* raw_refit,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& runtime_drivers
) {
    if (raw_refit == nullptr || raw_refit->type == JsonValue::Type::Null) return {};
    if (raw_refit->type != JsonValue::Type::Object) {
        throw std::runtime_error("morph runtime snapshot has invalid refit state");
    }
    auto refit = std::make_shared<MeshRefitRuntime>();
    refit->driver_submesh_indices = mesh_editor_snapshot_submesh_set(
        mesh_editor_snapshot_required_member(*raw_refit, "driver_submesh_indices", JsonValue::Type::Array),
        submeshes,
        "refit driver submeshes",
        false
    );
    if (refit->driver_submesh_indices != runtime_drivers) {
        throw std::runtime_error("morph runtime snapshot refit driver set does not match its runtime driver set");
    }
    refit->garment_submesh_indices = mesh_editor_snapshot_submesh_set(
        mesh_editor_snapshot_required_member(*raw_refit, "garment_submesh_indices", JsonValue::Type::Array),
        submeshes,
        "refit garment submeshes",
        false
    );
    for (const int index : refit->garment_submesh_indices) {
        if (refit->driver_submesh_indices.find(index) != refit->driver_submesh_indices.end()) {
            throw std::runtime_error("morph runtime snapshot refit driver and garment sets overlap");
        }
    }
    const JsonValue& raw_baselines = mesh_editor_snapshot_required_member(
        *raw_refit, "driver_baseline_positions", JsonValue::Type::Array
    );
    for (const JsonValue& item : raw_baselines.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid driver baseline");
        }
        int submesh_index = -1;
        if (!strict_int_or(item.get("submesh_index"), submesh_index)
            || refit->driver_submesh_indices.find(submesh_index) == refit->driver_submesh_indices.end()) {
            throw std::runtime_error("morph runtime snapshot has invalid driver baseline submesh");
        }
        std::vector<Vec3> positions = mesh_editor_snapshot_vec3s(
            mesh_editor_snapshot_required_member(item, "positions", JsonValue::Type::Array),
            "driver baseline positions"
        );
        const auto source = submeshes.find(submesh_index);
        if (source == submeshes.end() || positions.size() != source->second.vertices.size()
            || !refit->driver_baseline_positions.emplace(submesh_index, std::move(positions)).second) {
            throw std::runtime_error("morph runtime snapshot driver baseline topology does not match");
        }
    }
    if (refit->driver_baseline_positions.size() != refit->driver_submesh_indices.size()) {
        throw std::runtime_error("morph runtime snapshot is missing a driver baseline");
    }
    const JsonValue& raw_bindings = mesh_editor_snapshot_required_member(
        *raw_refit, "bindings", JsonValue::Type::Array
    );
    std::set<std::pair<int, int>> bound_vertices;
    refit->bindings.reserve(raw_bindings.array_value.size());
    for (const JsonValue& item : raw_bindings.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid refit binding");
        }
        MeshRefitVertexBindingRuntime binding;
        if (!strict_int_or(item.get("garment_submesh_index"), binding.garment_submesh_index)
            || !strict_int_or(item.get("garment_vertex_index"), binding.garment_vertex_index)
            || !strict_int_or(item.get("driver_submesh_index"), binding.driver_submesh_index)) {
            throw std::runtime_error("morph runtime snapshot has invalid refit binding indices");
        }
        const auto garment = submeshes.find(binding.garment_submesh_index);
        const auto driver = submeshes.find(binding.driver_submesh_index);
        if (refit->garment_submesh_indices.find(binding.garment_submesh_index)
                == refit->garment_submesh_indices.end()
            || refit->driver_submesh_indices.find(binding.driver_submesh_index)
                == refit->driver_submesh_indices.end()
            || garment == submeshes.end() || driver == submeshes.end()
            || binding.garment_vertex_index < 0
            || static_cast<std::size_t>(binding.garment_vertex_index) >= garment->second.vertices.size()
            || !bound_vertices.emplace(binding.garment_submesh_index, binding.garment_vertex_index).second) {
            throw std::runtime_error("morph runtime snapshot refit binding topology does not match");
        }
        const JsonValue& raw_vertices = mesh_editor_snapshot_required_member(
            item, "driver_vertices", JsonValue::Type::Array
        );
        const JsonValue& raw_barycentric = mesh_editor_snapshot_required_member(
            item, "barycentric", JsonValue::Type::Array
        );
        if (raw_vertices.array_value.size() != 3 || raw_barycentric.array_value.size() != 3) {
            throw std::runtime_error("morph runtime snapshot refit binding triangle is invalid");
        }
        for (std::size_t corner = 0; corner < 3; ++corner) {
            if (!strict_int_or(&raw_vertices.array_value[corner], binding.driver_vertices[corner])
                || binding.driver_vertices[corner] < 0
                || static_cast<std::size_t>(binding.driver_vertices[corner]) >= driver->second.vertices.size()
                || raw_barycentric.array_value[corner].type != JsonValue::Type::Number
                || !std::isfinite(raw_barycentric.array_value[corner].number_value)) {
                throw std::runtime_error("morph runtime snapshot refit binding triangle is invalid");
            }
            binding.barycentric[corner] = raw_barycentric.array_value[corner].number_value;
        }
        binding.distance = mesh_editor_snapshot_number(item, "distance");
        binding.baseline_normal = mesh_editor_snapshot_vec3(
            mesh_editor_snapshot_required_member(item, "baseline_normal", JsonValue::Type::Array),
            "refit baseline normal"
        );
        binding.normal_height = mesh_editor_snapshot_number(item, "normal_height");
        binding.rigid_local_offset = mesh_editor_snapshot_vec3(
            mesh_editor_snapshot_required_member(item, "rigid_local_offset", JsonValue::Type::Array),
            "refit rigid local offset"
        );
        binding.rigid_frame_valid = mesh_editor_snapshot_bool(item, "rigid_frame_valid");
        refit->bindings.push_back(binding);
    }
    std::size_t expected_binding_count = 0;
    for (const int index : refit->garment_submesh_indices) {
        expected_binding_count += submeshes.at(index).vertices.size();
    }
    if (refit->bindings.size() != expected_binding_count) {
        throw std::runtime_error("morph runtime snapshot is missing garment refit bindings");
    }
    const JsonValue& raw_settings = mesh_editor_snapshot_required_member(
        *raw_refit, "garment_settings", JsonValue::Type::Array
    );
    for (const JsonValue& item : raw_settings.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid garment settings");
        }
        int submesh_index = -1;
        if (!strict_int_or(item.get("submesh_index"), submesh_index)
            || refit->garment_submesh_indices.find(submesh_index) == refit->garment_submesh_indices.end()) {
            throw std::runtime_error("morph runtime snapshot garment settings topology does not match");
        }
        MeshRefitGarmentSettingsRuntime settings;
        settings.enabled = mesh_editor_snapshot_bool(item, "enabled");
        settings.intensity_percent = mesh_editor_snapshot_number(item, "intensity_percent");
        settings.mode = mesh_editor_snapshot_string(item, "mode");
        settings.clearance_percent = mesh_editor_snapshot_number(item, "clearance_percent");
        if (settings.intensity_percent < 0.0 || settings.intensity_percent > 200.0
            || (settings.mode != "surface" && settings.mode != "rigid")
            || settings.clearance_percent < 0.0 || settings.clearance_percent > 5.0
            || !refit->garment_settings.emplace(submesh_index, std::move(settings)).second) {
            throw std::runtime_error("morph runtime snapshot has invalid garment settings");
        }
    }
    refit->driver_diagonal = mesh_editor_snapshot_number(*raw_refit, "driver_diagonal");
    refit->maximum_distance = mesh_editor_snapshot_number(*raw_refit, "maximum_distance");
    refit->p95_distance = mesh_editor_snapshot_number(*raw_refit, "p95_distance");
    refit->warning_distance = mesh_editor_snapshot_number(*raw_refit, "warning_distance");
    refit->distance_warning = mesh_editor_snapshot_bool(*raw_refit, "distance_warning");
    refit->driver_triangle_count = mesh_editor_snapshot_integer(*raw_refit, "driver_triangle_count");
    refit->candidate_triangle_tests = mesh_editor_snapshot_integer(*raw_refit, "candidate_triangle_tests");
    if (refit->driver_diagonal < 0.0 || refit->maximum_distance < 0.0 || refit->p95_distance < 0.0
        || refit->warning_distance < 0.0) {
        throw std::runtime_error("morph runtime snapshot has invalid refit metrics");
    }
    return refit;
}

std::shared_ptr<MeshMorphRuntime> mesh_editor_morph_runtime_from_snapshot(
    const JsonValue& raw_runtime,
    const MeshEditorSession& session
) {
    if (raw_runtime.type != JsonValue::Type::Object) {
        throw std::runtime_error("morph runtime snapshot has invalid runtime state");
    }
    const auto& submeshes = mesh_editor_submeshes(session);
    auto runtime = std::make_shared<MeshMorphRuntime>();
    const JsonValue* raw_profile = raw_runtime.get("profile");
    if (raw_profile == nullptr) throw std::runtime_error("morph runtime snapshot is missing its profile");
    if (raw_profile->type != JsonValue::Type::Null) {
        runtime->profile = mesh_editor_morph_profile_from_json(raw_profile, submeshes);
        if (!runtime->profile) throw std::runtime_error("morph runtime snapshot has an empty profile id");
    }
    runtime->preset_id = mesh_editor_snapshot_string(raw_runtime, "preset_id");
    const JsonValue& raw_values = mesh_editor_snapshot_required_member(
        raw_runtime, "values", JsonValue::Type::Object
    );
    for (const auto& item : raw_values.object_value) {
        if (item.second.type != JsonValue::Type::Number || !std::isfinite(item.second.number_value)) {
            throw std::runtime_error("morph runtime snapshot has invalid slider values");
        }
        runtime->values[item.first] = item.second.number_value;
    }
    if (runtime->profile) {
        if (runtime->values.size() != runtime->profile->definitions.size()) {
            throw std::runtime_error("morph runtime snapshot slider values do not match its profile");
        }
        for (const auto& item : runtime->profile->definitions) {
            const auto value = runtime->values.find(item.first);
            if (value == runtime->values.end() || value->second < item.second.min_percent
                || value->second > item.second.max_percent) {
                throw std::runtime_error("morph runtime snapshot slider values do not match its profile");
            }
        }
    } else if (!runtime->values.empty() || !runtime->preset_id.empty()) {
        throw std::runtime_error("morph runtime snapshot has slider state without a profile");
    }
    const JsonValue& raw_layer = mesh_editor_snapshot_required_member(
        raw_runtime, "current_layer", JsonValue::Type::Array
    );
    for (const JsonValue& item : raw_layer.array_value) {
        if (item.type != JsonValue::Type::Object) {
            throw std::runtime_error("morph runtime snapshot has invalid current layer");
        }
        int submesh_index = -1;
        if (!strict_int_or(item.get("submesh_index"), submesh_index)) {
            throw std::runtime_error("morph runtime snapshot has invalid current layer submesh");
        }
        const auto submesh = submeshes.find(submesh_index);
        std::vector<Vec3> deltas = mesh_editor_snapshot_vec3s(
            mesh_editor_snapshot_required_member(item, "deltas", JsonValue::Type::Array),
            "current morph layer"
        );
        if (submesh == submeshes.end() || deltas.size() != submesh->second.vertices.size()
            || !runtime->current_layer.emplace(submesh_index, std::move(deltas)).second) {
            throw std::runtime_error("morph runtime snapshot current layer topology does not match");
        }
    }
    runtime->driver_submesh_indices = mesh_editor_snapshot_submesh_set(
        mesh_editor_snapshot_required_member(raw_runtime, "driver_submesh_indices", JsonValue::Type::Array),
        submeshes,
        "runtime driver submeshes",
        true
    );
    runtime->refit = mesh_editor_refit_from_snapshot(
        raw_runtime.get("refit"), submeshes, runtime->driver_submesh_indices
    );
    runtime->unbaked = mesh_editor_snapshot_bool(raw_runtime, "unbaked");
    if (runtime->unbaked != mesh_editor_morph_layer_has_value(runtime->current_layer)) {
        throw std::runtime_error("morph runtime snapshot unbaked state does not match its current layer");
    }
    runtime->state_revision = mesh_editor_snapshot_integer(raw_runtime, "state_revision");
    runtime->change_id = mesh_editor_snapshot_string(raw_runtime, "change_id");
    runtime->active_change_id = mesh_editor_snapshot_string(raw_runtime, "active_change_id");
    runtime->active_definition_id = mesh_editor_snapshot_string(raw_runtime, "active_definition_id");
    const long long active_change_update_count = mesh_editor_snapshot_integer(
        raw_runtime, "active_change_update_count"
    );
    if (active_change_update_count > INT_MAX) {
        throw std::runtime_error("morph runtime snapshot active gesture counter is invalid");
    }
    runtime->active_change_update_count = static_cast<int>(active_change_update_count);
    if (!runtime->active_change_id.empty() || !runtime->active_definition_id.empty()
        || runtime->active_change_update_count != 0) {
        throw std::runtime_error("morph runtime snapshot contains an unfinished gesture");
    }
    return runtime;
}

std::string mesh_editor_snapshot_normalized_path(std::string path) {
    for (char& ch : path) {
        if (ch == '\\') ch = '/';
        else ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    while (path.size() > 1 && path.back() == '/') path.pop_back();
    return path;
}

std::string mesh_editor_validate_morph_snapshot_path(const std::string& raw_path) {
    if (raw_path.empty() || raw_path.find("..") != std::string::npos) {
        throw std::runtime_error("morph runtime snapshot path is invalid");
    }
    const std::size_t separator = raw_path.find_last_of("/\\");
    if (separator == std::string::npos || separator + 1 >= raw_path.size()) {
        throw std::runtime_error("morph runtime snapshot path must be an absolute app-owned temp file");
    }
    const std::string filename = raw_path.substr(separator + 1);
    const std::string prefix = "cdmw_mesh_preview_delta_";
    const std::string suffix = "_morph_runtime_snapshot.json";
    if (filename.compare(0, prefix.size(), prefix) != 0
        || filename.size() < suffix.size()
        || filename.compare(filename.size() - suffix.size(), suffix.size(), suffix) != 0) {
        throw std::runtime_error("morph runtime snapshot path is not app-owned");
    }
    const char* temp_raw = std::getenv("TEMP");
    if (temp_raw == nullptr || *temp_raw == '\0') temp_raw = std::getenv("TMPDIR");
    if (temp_raw == nullptr || *temp_raw == '\0') temp_raw = std::getenv("TMP");
    if (temp_raw == nullptr || *temp_raw == '\0') {
        throw std::runtime_error("morph runtime snapshot temp root is unavailable");
    }
    const std::string parent = raw_path.substr(0, separator);
    if (mesh_editor_snapshot_normalized_path(parent)
        != mesh_editor_snapshot_normalized_path(temp_raw)) {
        throw std::runtime_error("morph runtime snapshot path escaped the app temp root");
    }
    return raw_path;
}

std::string mesh_editor_read_morph_snapshot_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) throw std::runtime_error("cannot open morph runtime snapshot");
    const std::streamoff end = input.tellg();
    if (end <= 0 || static_cast<unsigned long long>(end) > MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_MAX_BYTES) {
        throw std::runtime_error("morph runtime snapshot size is invalid");
    }
    std::string payload(static_cast<std::size_t>(end), '\0');
    input.seekg(0, std::ios::beg);
    input.read(&payload[0], end);
    if (!input) throw std::runtime_error("cannot read complete morph runtime snapshot");
    return payload;
}

void mesh_editor_write_morph_snapshot_file(const std::string& path, const std::string& payload) {
    if (payload.empty() || payload.size() > MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_MAX_BYTES) {
        throw std::runtime_error("morph runtime snapshot size is invalid");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("cannot open morph runtime snapshot output");
    output.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    output.flush();
    if (!output) {
        output.close();
        (void)std::remove(path.c_str());
        throw std::runtime_error("cannot write complete morph runtime snapshot");
    }
}

void mesh_editor_validate_morph_snapshot_file_identity(
    const JsonValue& request,
    const std::string& path,
    const std::string& payload
) {
    const long long declared_size = mesh_editor_snapshot_integer(request, "snapshot_byte_length", 1);
    if (static_cast<unsigned long long>(declared_size) != payload.size()) {
        throw std::runtime_error("morph runtime snapshot byte length does not match");
    }
    const std::string declared_sha256 = lower_ascii(mesh_editor_snapshot_string(request, "snapshot_sha256"));
    if (declared_sha256.size() != 64 || declared_sha256 != mesh_editor_snapshot_sha256(payload)) {
        throw std::runtime_error("morph runtime snapshot SHA-256 does not match");
    }
    (void)path;
}

void mesh_editor_validate_morph_snapshot_document(
    const JsonValue& document,
    const std::string& expected_snapshot_id
) {
    if (document.type != JsonValue::Type::Object
        || mesh_editor_snapshot_string(document, "schema") != MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA
        || mesh_editor_snapshot_integer(document, "version", 1) != 1
        || mesh_editor_snapshot_string(document, "snapshot_id") != expected_snapshot_id
        || mesh_editor_snapshot_string(document, "source_session_id").empty()) {
        throw std::runtime_error("morph runtime snapshot identity does not match");
    }
    const std::string topology_digest = lower_ascii(
        mesh_editor_snapshot_string(document, "topology_digest")
    );
    if (topology_digest.size() != 64
        || mesh_editor_snapshot_string(document, "topology_digest_algorithm") != "sha256") {
        throw std::runtime_error("morph runtime snapshot topology digest is invalid");
    }
    (void)mesh_editor_snapshot_integer(document, "retained_bytes", 1);
    (void)mesh_editor_snapshot_integer(document, "morph_state_revision");
    (void)mesh_editor_snapshot_required_member(document, "runtime", JsonValue::Type::Object);
}

std::string mesh_editor_morph_snapshot_create_session_report(
    const JsonValue& root,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (session.active_stroke.active
        || (session.morph && !session.morph->active_change_id.empty())) {
        throw std::runtime_error("finish or cancel the active mesh gesture before capturing Morph & Refit state");
    }
    const std::string snapshot_id = mesh_editor_snapshot_string(root, "snapshot_id");
    if (snapshot_id.empty() || snapshot_id.size() > 128) {
        throw std::runtime_error("morph runtime snapshot requires a bounded snapshot_id");
    }
    const std::string output_path = mesh_editor_validate_morph_snapshot_path(
        mesh_editor_snapshot_string(root, "snapshot_output_path")
    );
    const std::string runtime_payload = mesh_editor_morph_runtime_snapshot_payload(session);
    const std::string topology_digest = mesh_editor_morph_topology_digest(session);
    std::ostringstream document_stream;
    document_stream << "{\"schema\":";
    write_escaped(document_stream, MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA);
    document_stream << ",\"version\":1,\"snapshot_id\":";
    write_escaped(document_stream, snapshot_id);
    document_stream << ",\"source_session_id\":";
    write_escaped(document_stream, session_id);
    document_stream << ",\"topology_digest_algorithm\":\"sha256\",\"topology_digest\":";
    write_escaped(document_stream, topology_digest);
    document_stream << ",\"retained_bytes\":" << runtime_payload.size()
        << ",\"morph_state_revision\":" << session.morph_state_revision
        << ",\"runtime\":" << runtime_payload << '}';
    const std::string document = document_stream.str();
    mesh_editor_write_morph_snapshot_file(output_path, document);
    const std::string sha256 = mesh_editor_snapshot_sha256(document);
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\","
           "\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_snapshot_create\","
           "\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"snapshot\":{\"schema\":";
    write_escaped(out, MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA);
    out << ",\"version\":1,\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << ",\"source_session_id\":";
    write_escaped(out, session_id);
    out << ",\"path\":";
    write_escaped(out, output_path);
    out << ",\"byte_length\":" << document.size() << ",\"sha256\":";
    write_escaped(out, sha256);
    out << ",\"topology_digest\":";
    write_escaped(out, topology_digest);
    out << ",\"retained_bytes\":" << runtime_payload.size()
        << "},\"metrics\":{\"cpp_ms\":" << std::setprecision(17) << cpp_ms
        << ",\"io_serialization_ms\":0}}";
    return out.str();
}

std::string mesh_editor_morph_snapshot_restore_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const std::string snapshot_id = mesh_editor_snapshot_string(root, "snapshot_id");
    const std::string path = mesh_editor_validate_morph_snapshot_path(
        mesh_editor_snapshot_string(root, "snapshot_path")
    );
    const std::string payload = mesh_editor_read_morph_snapshot_file(path);
    mesh_editor_validate_morph_snapshot_file_identity(root, path, payload);
    const JsonValue document = JsonParser(payload).parse();
    mesh_editor_validate_morph_snapshot_document(document, snapshot_id);
    const std::string expected_topology = lower_ascii(
        mesh_editor_snapshot_string(document, "topology_digest")
    );
    const std::string actual_topology = mesh_editor_morph_topology_digest(session);
    if (expected_topology != actual_topology) {
        throw std::runtime_error("morph runtime snapshot topology does not match the target session");
    }
    std::shared_ptr<MeshMorphRuntime> restored = mesh_editor_morph_runtime_from_snapshot(
        mesh_editor_snapshot_required_member(document, "runtime", JsonValue::Type::Object), session
    );
    const long long snapshot_revision = mesh_editor_snapshot_integer(document, "morph_state_revision");
    session.morph_state_revision = std::max(
        session.morph_state_revision,
        std::max(snapshot_revision, restored->state_revision)
    );
    restored->state_revision = ++session.morph_state_revision;
    restored->active_change_id.clear();
    restored->active_definition_id.clear();
    restored->active_change_update_count = 0;
    session.morph = std::move(restored);
    session.active_stroke = MeshEditorStroke{};
    session.undo_stack.clear();
    session.redo_stack.clear();
    ++session.stroke_revision;
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\","
           "\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_snapshot_restore\","
           "\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << ",\"topology_digest\":";
    write_escaped(out, actual_topology);
    out << ",\"retained_bytes\":" << mesh_editor_snapshot_integer(document, "retained_bytes", 1)
        << ",\"geometry_recomposed\":false,\"history_cleared\":true,\"gesture_cleared\":true,";
    mesh_editor_write_session_counts(out, session);
    out << ",\"morph_state\":";
    mesh_editor_write_morph_state(out, session);
    out << ",\"metrics\":{\"cpp_ms\":" << std::setprecision(17) << cpp_ms
        << ",\"io_serialization_ms\":0}}";
    return out.str();
}

std::string mesh_editor_morph_snapshot_dispose_report(
    const JsonValue& root,
    const std::string& session_id,
    const std::chrono::steady_clock::time_point& started
) {
    const std::string snapshot_id = mesh_editor_snapshot_string(root, "snapshot_id");
    const std::string path = mesh_editor_validate_morph_snapshot_path(
        mesh_editor_snapshot_string(root, "snapshot_path")
    );
    const std::string payload = mesh_editor_read_morph_snapshot_file(path);
    mesh_editor_validate_morph_snapshot_file_identity(root, path, payload);
    const JsonValue document = JsonParser(payload).parse();
    mesh_editor_validate_morph_snapshot_document(document, snapshot_id);
    if (mesh_editor_snapshot_string(document, "source_session_id") != session_id) {
        throw std::runtime_error("morph runtime snapshot dispose session does not match its owner");
    }
    if (std::remove(path.c_str()) != 0) {
        throw std::runtime_error("cannot dispose morph runtime snapshot");
    }
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\","
           "\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_snapshot_dispose\","
           "\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << ",\"disposed\":true,\"metrics\":{\"cpp_ms\":" << std::setprecision(17) << cpp_ms
        << ",\"io_serialization_ms\":0}}";
    return out.str();
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
