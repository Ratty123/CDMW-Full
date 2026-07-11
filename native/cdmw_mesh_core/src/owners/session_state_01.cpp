JsonValue mesh_editor_json_number(double value) {
    JsonValue result;
    result.type = JsonValue::Type::Number;
    result.number_value = value;
    return result;
}

JsonValue mesh_editor_json_string(const std::string& value) {
    JsonValue result;
    result.type = JsonValue::Type::String;
    result.string_value = value;
    return result;
}

JsonValue mesh_editor_json_bool(bool value) {
    JsonValue result;
    result.type = JsonValue::Type::Bool;
    result.bool_value = value;
    return result;
}

std::string mesh_editor_safe_path_token(const std::string& value) {
    std::string result;
    result.reserve(value.size());
    for (const char ch : value) {
        const unsigned char raw = static_cast<unsigned char>(ch);
        if ((raw >= 'a' && raw <= 'z')
            || (raw >= 'A' && raw <= 'Z')
            || (raw >= '0' && raw <= '9')
            || ch == '-' || ch == '_') {
            result.push_back(ch);
        } else {
            result.push_back('_');
        }
    }
    return result.empty() ? "session" : result;
}

std::string mesh_editor_join_path(const std::string& directory, const std::string& filename) {
    if (directory.empty()) {
        return std::string();
    }
    const char last = directory[directory.size() - 1];
    if (last == '/' || last == '\\') {
        return directory + filename;
    }
    return directory + "/" + filename;
}

std::string mesh_editor_delta_path(
    const std::string& directory,
    const std::string& session_id,
    int submesh_index,
    const std::string& role,
    const std::string& suffix
) {
    std::ostringstream name;
    name << "mesh_editor_" << mesh_editor_safe_path_token(session_id)
         << "_" << submesh_index << "_" << role << suffix;
    return mesh_editor_join_path(directory, name.str());
}

void mesh_editor_add_delta_output_paths(
    JsonValue& item,
    const std::string& directory,
    const std::string& session_id,
    int submesh_index
) {
    if (directory.empty()) {
        return;
    }
    item.object_value["changed_vertices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "changed_vertices", ".bin"));
    item.object_value["changed_positions_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "changed_positions", ".bin"));
    item.object_value["before_positions_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "before_positions", ".bin"));
    item.object_value["preview_vertex_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "preview_vertices", ".bin"));
    item.object_value["vertices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "vertices", ".bin"));
    item.object_value["faces_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "faces", ".bin"));
    item.object_value["normals_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "normals", ".bin"));
    item.object_value["uvs_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "uvs", ".bin"));
    item.object_value["tangents_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "tangents", ".bin"));
    item.object_value["tangent_signs_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "tangent_signs", ".bin"));
    item.object_value["bone_counts_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "bone_counts", ".bin"));
    item.object_value["bone_indices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "bone_indices", ".bin"));
    item.object_value["bone_weights_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "bone_weights", ".bin"));
    item.object_value["source_vertex_map_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "source_vertex_map", ".bin"));
    item.object_value["source_vertex_offsets_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "source_vertex_offsets", ".bin"));
    item.object_value["copy_vertex_indices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "copy_vertex_indices", ".bin"));
    item.object_value["vertex_blend_indices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "vertex_blend_indices", ".bin"));
    item.object_value["vertex_blend_factors_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "vertex_blend_factors", ".bin"));
    item.object_value["index_map_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "index_map", ".bin"));
    item.object_value["preview_triangle_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "preview_triangles", ".bin"));
}

void mesh_editor_set_result_output_paths(
    SubmeshMeshEditResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.changed_positions_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_positions", ".bin");
    result.vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "vertices", ".bin");
    result.faces_path = mesh_editor_delta_path(directory, session_id, result.index, "faces", ".bin");
    result.normals_path = mesh_editor_delta_path(directory, session_id, result.index, "normals", ".bin");
    result.uvs_path = mesh_editor_delta_path(directory, session_id, result.index, "uvs", ".bin");
    result.tangents_path = mesh_editor_delta_path(directory, session_id, result.index, "tangents", ".bin");
    result.tangent_signs_path = mesh_editor_delta_path(directory, session_id, result.index, "tangent_signs", ".bin");
    result.bone_counts_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_counts", ".bin");
    result.bone_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_indices", ".bin");
    result.bone_weights_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_weights", ".bin");
    result.source_vertex_map_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_map", ".bin");
    result.source_vertex_offsets_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_offsets", ".bin");
    result.copy_vertex_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "copy_vertex_indices", ".bin");
    result.vertex_blend_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "vertex_blend_indices", ".bin");
    result.vertex_blend_factors_path = mesh_editor_delta_path(directory, session_id, result.index, "vertex_blend_factors", ".bin");
    result.index_map_path = mesh_editor_delta_path(directory, session_id, result.index, "index_map", ".bin");
    result.preview_triangle_path = mesh_editor_delta_path(directory, session_id, result.index, "preview_triangles", ".bin");
}

bool mesh_editor_is_normal_operation(const std::string& operation) {
    return operation == "recalculate_normals"
        || operation == "weighted_normals"
        || operation == "flip_normals"
        || operation == "sharpen_normals"
        || operation == "soften_normals"
        || operation == "copy_normals";
}

bool mesh_editor_is_tangent_operation(const std::string& operation) {
    return operation == "generate_tangents";
}

bool mesh_editor_is_uv_operation(const std::string& operation) {
    return operation == "uv_transform";
}

void mesh_editor_set_normal_result_output_paths(
    SubmeshNormalsResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.normals_path = mesh_editor_delta_path(directory, session_id, result.index, "normals", ".bin");
    result.faces_path = mesh_editor_delta_path(directory, session_id, result.index, "faces", ".bin");
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.preview_vertex_path = mesh_editor_delta_path(directory, session_id, result.index, "normal_preview_vertices", ".bin");
    result.preview_triangle_path = mesh_editor_delta_path(directory, session_id, result.index, "normal_preview_triangles", ".bin");
}

bool mesh_editor_normals_result_changed(const SubmeshNormalsResult& result) {
    return !result.changed_vertices.empty() || !result.faces.empty();
}

SubmeshMeshEditResult mesh_editor_result_from_normals_result(const SubmeshNormalsResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "normals";
    result.changed_vertices = source.changed_vertices;
    result.changed_positions.reserve(source.changed_vertices.size());
    for (const int vertex_index : source.changed_vertices) {
        if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < source.vertices.size()) {
            result.changed_positions.push_back(source.vertices[static_cast<std::size_t>(vertex_index)]);
        }
    }
    result.changed_positions_path = source.preview_vertex_path;
    result.faces = source.faces;
    result.normals = source.normals;
    result.preview_uvs = source.uvs;
    result.source_vertex_map = source.source_vertex_map;
    if (!source.faces.empty()) {
        result.vertices = source.vertices;
        result.preview_triangle_path = source.preview_triangle_path;
    }
    result.sparse = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_normals_results(
    const std::vector<SubmeshNormalsResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshNormalsResult& source : sources) {
        if (mesh_editor_normals_result_changed(source)) {
            results.push_back(mesh_editor_result_from_normals_result(source));
        }
    }
    return results;
}

SubmeshNormalsResult mesh_editor_normal_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& operation,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshNormalsResult result;
    result.index = submesh_index;
    result.vertices = restored.vertices;
    result.normals = restored.normals;
    result.uvs = restored.uvs;
    result.source_vertex_map = restored.source_vertex_map;
    if (operation == "flip_normals" && current.faces != restored.faces) {
        result.faces = restored.faces;
    }
    mesh_editor_set_normal_result_output_paths(result, delta_output_dir, session_id);

    if (current.normals.size() == restored.normals.size()) {
        for (std::size_t normal_index = 0; normal_index < restored.normals.size(); ++normal_index) {
            if (!same_vec3(current.normals[normal_index], restored.normals[normal_index])) {
                result.changed_vertices.push_back(static_cast<int>(normal_index));
            }
        }
    } else {
        result.changed_vertices.reserve(restored.normals.size());
        for (std::size_t normal_index = 0; normal_index < restored.normals.size(); ++normal_index) {
            result.changed_vertices.push_back(static_cast<int>(normal_index));
        }
    }
    return result;
}

void mesh_editor_set_uv_result_output_paths(
    SubmeshUvTransformResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.uvs_path = mesh_editor_delta_path(directory, session_id, result.index, "uvs", ".bin");
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.preview_vertex_path = mesh_editor_delta_path(directory, session_id, result.index, "uv_preview_vertices", ".bin");
}

bool mesh_editor_uv_result_changed(const SubmeshUvTransformResult& result) {
    return result.clear_uvs || !result.changed_vertices.empty() || result.status != "ok";
}

SubmeshMeshEditResult mesh_editor_result_from_uv_result(const SubmeshUvTransformResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "uv_transform";
    result.changed_vertices = source.changed_vertices;
    result.changed_positions_path = source.preview_vertex_path;
    if (source.vertices.size() == source.uvs.size()) {
        result.changed_positions.reserve(source.changed_vertices.size());
        for (const int vertex_index : source.changed_vertices) {
            if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < source.vertices.size()) {
                result.changed_positions.push_back(source.vertices[static_cast<std::size_t>(vertex_index)]);
            }
        }
    }
    result.preview_normals = source.normals;
    result.preview_uvs = source.uvs;
    result.sparse = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_uv_results(
    const std::vector<SubmeshUvTransformResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshUvTransformResult& source : sources) {
        if (mesh_editor_uv_result_changed(source)) {
            results.push_back(mesh_editor_result_from_uv_result(source));
        }
    }
    return results;
}

bool mesh_editor_auto_uv_result_changed(const SubmeshAutoUvResult& result) {
    return result.status == "ok" && (result.topology_changed || !result.changed_vertices.empty());
}

SubmeshMeshEditResult mesh_editor_result_from_auto_uv_result(
    const SubmeshAutoUvResult& source,
    const MeshSessionSubmesh* current
) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "auto_uv";
    result.topology_changed = source.topology_changed;
    result.vertices = source.vertices;
    result.faces = source.faces;
    result.normals = source.normals;
    result.preview_uvs = source.uvs;
    result.tangents = source.tangents;
    result.tangent_signs = source.tangent_signs;
    result.bones = source.bones;
    result.source_vertex_map = source.source_vertex_map;
    result.source_vertex_offsets = source.source_vertex_offsets;
    result.changed_vertices = source.changed_vertices;
    result.vertices_path = source.vertices_path;
    result.faces_path = source.faces_path;
    result.uvs_path = source.uvs_path;
    result.normals_path = source.normals_path;
    result.tangents_path = source.tangents_path;
    result.tangent_signs_path = source.tangent_signs_path;
    result.bone_counts_path = source.bone_counts_path;
    result.bone_indices_path = source.bone_indices_path;
    result.bone_weights_path = source.bone_weights_path;
    result.source_vertex_map_path = source.source_vertex_map_path;
    result.source_vertex_offsets_path = source.source_vertex_offsets_path;
    result.changed_vertices_path = source.changed_vertices_path;
    if (current != nullptr && current->source_face_indices.size() == result.faces.size()) {
        result.source_face_indices = current->source_face_indices;
    } else {
        result.source_face_indices = identity_indices(result.faces.size());
    }
    result.added_vertices = std::max(0, source.output_vertex_count - source.input_vertex_count);
    result.removed_vertices = std::max(0, source.input_vertex_count - source.output_vertex_count);
    result.added_faces = std::max(0, source.output_face_count - source.input_face_count);
    result.removed_faces = std::max(0, source.input_face_count - source.output_face_count);
    return result;
}

MeshSessionSubmesh mesh_editor_submesh_after_auto_uv(
    const MeshSessionSubmesh& current,
    const SubmeshAutoUvResult& source
) {
    MeshSessionSubmesh updated = current;
    if (source.topology_changed) {
        updated.vertices = source.vertices;
        updated.faces = source.faces;
        updated.source_face_indices = current.source_face_indices.size() == source.faces.size()
            ? current.source_face_indices
            : identity_indices(source.faces.size());
        updated.normals = source.normals.size() == source.vertices.size()
            ? source.normals
            : compute_smooth_normals(source.vertices, source.faces);
        updated.tangents = source.tangents.size() == source.vertices.size() ? source.tangents : std::vector<Vec3>();
        updated.tangent_signs = source.tangent_signs.size() == source.vertices.size() ? source.tangent_signs : std::vector<double>();
        if (valid_bone_assignments(source.bones) && source.bones.indices.size() == source.vertices.size()) {
            updated.bone_indices = source.bones.indices;
            updated.bone_weights = source.bones.weights;
        } else {
            updated.bone_indices.clear();
            updated.bone_weights.clear();
        }
        updated.source_vertex_map = source.source_vertex_map.size() == source.vertices.size()
            ? source.source_vertex_map
            : std::vector<int>();
        updated.source_vertex_offsets = source.source_vertex_offsets.size() == source.vertices.size()
            ? source.source_vertex_offsets
            : std::vector<int>();
    }
    if (source.uvs.size() == updated.vertices.size()) {
        updated.uvs = source.uvs;
    }
    return updated;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_auto_uv_results(
    const std::vector<SubmeshAutoUvResult>& sources,
    const std::map<int, MeshSessionSubmesh>& before_submeshes,
    std::map<int, MeshSessionSubmesh>& native_session
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshAutoUvResult& source : sources) {
        SubmeshAutoUvResult normalized = source;
        const auto before_found = before_submeshes.find(source.index);
        if (normalized.changed_vertices.empty()
            && before_found != before_submeshes.end()
            && normalized.uvs.size() == before_found->second.uvs.size()) {
            for (std::size_t index = 0; index < normalized.uvs.size(); ++index) {
                if (!same_vec2(before_found->second.uvs[index], normalized.uvs[index])) {
                    normalized.changed_vertices.push_back(static_cast<int>(index));
                }
            }
        }
        if (!mesh_editor_auto_uv_result_changed(normalized)) {
            continue;
        }
        const auto current_found = native_session.find(source.index);
        const MeshSessionSubmesh* current = before_found != before_submeshes.end()
            ? &before_found->second
            : (current_found != native_session.end() ? &current_found->second : nullptr);
        results.push_back(mesh_editor_result_from_auto_uv_result(normalized, current));
        if (normalized.status == "ok" && current != nullptr && normalized.uvs.size() == normalized.vertices.size()) {
            native_session[normalized.index] = mesh_editor_submesh_after_auto_uv(*current, normalized);
        }
    }
    return results;
}

SubmeshUvTransformResult mesh_editor_uv_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshUvTransformResult result;
    result.index = submesh_index;
    mesh_editor_set_uv_result_output_paths(result, delta_output_dir, session_id);
    if (restored.uvs.size() != restored.vertices.size()) {
        result.clear_uvs = true;
        const std::size_t vertex_count = std::max(current.vertices.size(), current.uvs.size());
        result.changed_vertices.reserve(vertex_count);
        for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
            result.changed_vertices.push_back(static_cast<int>(vertex_index));
        }
        return result;
    }
    result.uvs = restored.uvs;
    if (current.uvs.size() == restored.uvs.size()) {
        for (std::size_t uv_index = 0; uv_index < restored.uvs.size(); ++uv_index) {
            if (!same_vec2(current.uvs[uv_index], restored.uvs[uv_index])) {
                result.changed_vertices.push_back(static_cast<int>(uv_index));
            }
        }
    } else {
        result.changed_vertices.reserve(restored.uvs.size());
        for (std::size_t uv_index = 0; uv_index < restored.uvs.size(); ++uv_index) {
            result.changed_vertices.push_back(static_cast<int>(uv_index));
        }
    }
    return result;
}

void mesh_editor_set_tangent_result_output_paths(
    SubmeshTangentsResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "vertices", ".bin");
    result.faces_path = mesh_editor_delta_path(directory, session_id, result.index, "faces", ".bin");
    result.normals_path = mesh_editor_delta_path(directory, session_id, result.index, "normals", ".bin");
    result.uvs_path = mesh_editor_delta_path(directory, session_id, result.index, "uvs", ".bin");
    result.tangents_path = mesh_editor_delta_path(directory, session_id, result.index, "tangents", ".bin");
    result.tangent_signs_path = mesh_editor_delta_path(directory, session_id, result.index, "tangent_signs", ".bin");
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.bone_counts_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_counts", ".bin");
    result.bone_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_indices", ".bin");
    result.bone_weights_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_weights", ".bin");
    result.source_vertex_map_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_map", ".bin");
    result.source_vertex_offsets_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_offsets", ".bin");
}

bool mesh_editor_tangents_result_changed(const SubmeshTangentsResult& result) {
    return result.clear_tangents || result.topology_split_applied || !result.changed_vertices.empty();
}

SubmeshMeshEditResult mesh_editor_result_from_tangents_result(const SubmeshTangentsResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "generate_tangents";
    result.topology_changed = source.topology_split_applied;
    result.changed_vertices = source.changed_vertices;
    if (source.topology_split_applied) {
        result.vertices = source.vertices;
        result.faces = source.faces;
        result.normals = source.normals;
        result.preview_uvs = source.uvs;
        result.tangents = source.tangents;
        result.tangent_signs = source.tangent_signs;
        result.bones = source.bones;
        result.source_vertex_map = source.source_vertex_map;
        result.source_vertex_offsets = source.source_vertex_offsets;
    }
    result.sparse = !source.topology_split_applied;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_tangents_results(
    const std::vector<SubmeshTangentsResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshTangentsResult& source : sources) {
        if (mesh_editor_tangents_result_changed(source)) {
            results.push_back(mesh_editor_result_from_tangents_result(source));
        }
    }
    return results;
}

SubmeshTangentsResult mesh_editor_tangent_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshTangentsResult result;
    result.index = submesh_index;
    result.tangent_backend = "history";
    mesh_editor_set_tangent_result_output_paths(result, delta_output_dir, session_id);
    if (restored.tangents.size() != restored.vertices.size()) {
        result.clear_tangents = true;
        const std::size_t vertex_count = std::max(current.vertices.size(), current.tangents.size());
        result.changed_vertices.reserve(vertex_count);
        for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
            result.changed_vertices.push_back(static_cast<int>(vertex_index));
        }
        return result;
    }
    result.tangents = restored.tangents;
    if (current.tangents.size() == restored.tangents.size()) {
        for (std::size_t tangent_index = 0; tangent_index < restored.tangents.size(); ++tangent_index) {
            if (!same_vec3(current.tangents[tangent_index], restored.tangents[tangent_index])) {
                result.changed_vertices.push_back(static_cast<int>(tangent_index));
            }
        }
    } else {
        result.changed_vertices.reserve(restored.tangents.size());
        for (std::size_t tangent_index = 0; tangent_index < restored.tangents.size(); ++tangent_index) {
            result.changed_vertices.push_back(static_cast<int>(tangent_index));
        }
    }
    return result;
}

SubmeshMeshEditResult mesh_editor_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& action,
    bool history_topology_changed,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshMeshEditResult result;
    result.index = submesh_index;
    result.action = action;
    result.topology_changed = history_topology_changed
        || current.vertices.size() != restored.vertices.size()
        || current.faces != restored.faces;
    const bool material_metadata_changed = !mesh_editor_same_material_metadata(current, restored);
    if (result.topology_changed || material_metadata_changed) {
        result.name = restored.name;
        result.material = restored.material;
        result.texture = restored.texture;
        result.extra_attrs = restored.extra_attrs;
        result.material_metadata_changed = true;
    }
    result.added_vertices = static_cast<int>(restored.vertices.size() > current.vertices.size() ? restored.vertices.size() - current.vertices.size() : 0);
    result.removed_vertices = static_cast<int>(current.vertices.size() > restored.vertices.size() ? current.vertices.size() - restored.vertices.size() : 0);
    result.added_faces = static_cast<int>(restored.faces.size() > current.faces.size() ? restored.faces.size() - current.faces.size() : 0);
    result.removed_faces = static_cast<int>(current.faces.size() > restored.faces.size() ? current.faces.size() - restored.faces.size() : 0);
    mesh_editor_set_result_output_paths(result, delta_output_dir, session_id);

    if (result.topology_changed || material_metadata_changed) {
        result.vertices = restored.vertices;
        result.faces = restored.faces;
        result.normals = restored.normals;
        result.preview_uvs = restored.uvs;
        result.tangents = restored.tangents;
        result.tangent_signs = restored.tangent_signs;
        result.bones.indices = restored.bone_indices;
        result.bones.weights = restored.bone_weights;
        result.source_vertex_map = restored.source_vertex_map;
        result.source_vertex_offsets = restored.source_vertex_offsets;
        result.suppress_vertex_remap_report = true;
    }
    if (result.topology_changed) {
        return result;
    }

    result.sparse = true;
    const std::size_t vertex_count = std::min(current.vertices.size(), restored.vertices.size());
    for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
        if (current.vertices[vertex_index] != restored.vertices[vertex_index]) {
            result.changed_vertices.push_back(static_cast<int>(vertex_index));
            result.changed_positions.push_back(restored.vertices[vertex_index]);
        }
    }
    return result;
}

bool mesh_editor_key_to_index(const std::string& text, int& output) {
    if (text.empty()) {
        return false;
    }
    char* end = nullptr;
    errno = 0;
    const long parsed = std::strtol(text.c_str(), &end, 10);
    if (errno != 0 || end == text.c_str() || *end != '\0' || parsed < 0 || parsed > INT_MAX) {
        return false;
    }
    output = static_cast<int>(parsed);
    return true;
}

std::set<int> mesh_editor_indices_from_json(const JsonValue* value) {
    std::set<int> result;
    if (value == nullptr) {
        return result;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const std::string& binary_key : {"indices_binary", "selected_vertices_binary", "selected_faces_binary"}) {
            if (value->get(binary_key) != nullptr) {
                const std::vector<int> values = int_vector_from_binary_or_json(*value, binary_key, "indices", "start", "count");
                for (const int index : values) {
                    if (index >= 0) {
                        result.insert(index);
                    }
                }
            }
        }
        if (!result.empty()) {
            return result;
        }
        const int start = int_or(value->get("start"), int_or(value->get("selected_start"), -1));
        const int count = int_or(value->get("count"), int_or(value->get("selected_count"), 0));
        if (start >= 0 && count > 0) {
            for (int offset = 0; offset < count; ++offset) {
                result.insert(start + offset);
            }
        }
        const JsonValue* indices = value->get("indices");
        if (indices != nullptr) {
            const std::set<int> explicit_indices = mesh_editor_indices_from_json(indices);
            result.insert(explicit_indices.begin(), explicit_indices.end());
        }
        const JsonValue* vertices = value->get("vertices");
        if (vertices != nullptr) {
            const std::set<int> explicit_indices = mesh_editor_indices_from_json(vertices);
            result.insert(explicit_indices.begin(), explicit_indices.end());
        }
        const JsonValue* faces = value->get("faces");
        if (faces != nullptr) {
            const std::set<int> explicit_indices = mesh_editor_indices_from_json(faces);
            result.insert(explicit_indices.begin(), explicit_indices.end());
        }
        return result;
    }
    if (value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        int index = -1;
        if (strict_int_or(&item, index) && index >= 0) {
            result.insert(index);
        }
    }
    return result;
}

std::set<std::array<int, 2>> mesh_editor_edges_from_json(const JsonValue* value) {
    std::set<std::array<int, 2>> result;
    if (value == nullptr) {
        return result;
    }
    if (value->type == JsonValue::Type::Object) {
        const JsonValue* binary = value->get("edges_binary");
        if (binary == nullptr) {
            binary = value->get("selected_edges_binary");
        }
        if (binary == nullptr) {
            binary = value->get("indices_binary");
        }
        if (binary != nullptr) {
            const std::vector<int> raw = int_vector_from_binary(binary);
            for (std::size_t offset = 0; offset + 1 < raw.size(); offset += 2) {
                const int left = raw[offset];
                const int right = raw[offset + 1];
                if (left >= 0 && right >= 0 && left != right) {
                    result.insert(edge_key(left, right));
                }
            }
            return result;
        }
        const JsonValue* edges = value->get("edges");
        if (edges == nullptr) {
            edges = value->get("indices");
        }
        if (edges == nullptr) {
            edges = value->get("selected_edges");
        }
        return mesh_editor_edges_from_json(edges);
    }
    if (value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        int left = -1;
        int right = -1;
        if (strict_int_or(&item.array_value[0], left) && strict_int_or(&item.array_value[1], right) && left >= 0 && right >= 0 && left != right) {
            result.insert(edge_key(left, right));
        }
    }
    return result;
}

const JsonValue* mesh_editor_group_values(const JsonValue& item, const std::string& preferred_key) {
    if (const JsonValue* value = item.get("indices")) {
        return value;
    }
    if (const JsonValue* value = item.get(preferred_key)) {
        return value;
    }
    if (const JsonValue* value = item.get("selected")) {
        return value;
    }
    return &item;
}

std::vector<int> mesh_editor_index_vector_from_json(const JsonValue* value) {
    std::vector<int> result;
    if (value == nullptr) {
        return result;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const std::string& binary_key : {"indices_binary", "selected_vertices_binary", "selected_faces_binary"}) {
            if (value->get(binary_key) != nullptr) {
                const std::vector<int> values = int_vector_from_binary_or_json(
                    *value,
                    binary_key,
                    "indices",
                    "start",
                    "count"
                );
                for (const int index : values) {
                    if (index >= 0) {
                        result.push_back(index);
                    }
                }
                if (!result.empty()) {
                    return result;
                }
            }
        }
        const int start = int_or(value->get("start"), int_or(value->get("selected_start"), -1));
        const int count = int_or(value->get("count"), int_or(value->get("selected_count"), 0));
        if (start >= 0 && count > 0) {
            result.reserve(static_cast<std::size_t>(count));
            for (int offset = 0; offset < count; ++offset) {
                result.push_back(start + offset);
            }
            return result;
        }
        for (const std::string& key : {"indices", "vertices", "faces"}) {
            if (const JsonValue* nested = value->get(key)) {
                result = mesh_editor_index_vector_from_json(nested);
                if (!result.empty()) {
                    return result;
                }
            }
        }
        return result;
    }
    if (value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        int index = -1;
        if (strict_int_or(&item, index) && index >= 0) {
            result.push_back(index);
        }
    }
    return result;
}
