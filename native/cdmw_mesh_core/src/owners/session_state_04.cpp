bool mesh_editor_same_material_metadata(const MeshSessionSubmesh& left, const MeshSessionSubmesh& right) {
    return left.material == right.material
        && left.texture == right.texture
        && mesh_editor_extra_attrs_equal(left.extra_attrs, right.extra_attrs);
}

template <typename T>
MeshEditorChannelDelta<T> mesh_editor_make_channel_delta(
    const std::vector<T>& before,
    const std::vector<T>& after
) {
    MeshEditorChannelDelta<T> delta;
    delta.before_size = before.size();
    delta.after_size = after.size();
    if (before.size() != after.size()) {
        delta.replacement = true;
        delta.before_replacement = before;
        delta.after_replacement = after;
        return delta;
    }
    for (std::size_t index = 0; index < before.size(); ++index) {
        if (before[index] == after[index]) {
            continue;
        }
        delta.indices.push_back(static_cast<int>(index));
        delta.before_values.push_back(before[index]);
        delta.after_values.push_back(after[index]);
    }
    return delta;
}

template <typename T>
bool mesh_editor_channel_delta_empty(const MeshEditorChannelDelta<T>& delta) {
    return !delta.replacement && delta.indices.empty();
}

template <typename T>
void mesh_editor_apply_channel_delta(
    std::vector<T>& target,
    const MeshEditorChannelDelta<T>& delta,
    bool restore_before
) {
    if (delta.replacement) {
        target = restore_before ? delta.before_replacement : delta.after_replacement;
        return;
    }
    if (delta.indices.size() != delta.before_values.size() || delta.indices.size() != delta.after_values.size()) {
        throw std::runtime_error("invalid mesh editor history channel delta");
    }
    const std::vector<T>& values = restore_before ? delta.before_values : delta.after_values;
    for (std::size_t position = 0; position < delta.indices.size(); ++position) {
        const int index = delta.indices[position];
        if (index < 0 || static_cast<std::size_t>(index) >= target.size()) {
            throw std::runtime_error("mesh editor history channel index out of range");
        }
        target[static_cast<std::size_t>(index)] = values[position];
    }
}

template <typename T>
bool mesh_editor_can_merge_channel_delta(
    const MeshEditorChannelDelta<T>& target,
    const MeshEditorChannelDelta<T>& update
) {
    return mesh_editor_channel_delta_empty(update)
        || mesh_editor_channel_delta_empty(target)
        || (!target.replacement && !update.replacement && target.after_size == update.before_size);
}

template <typename T>
bool mesh_editor_merge_channel_delta(
    MeshEditorChannelDelta<T>& target,
    const MeshEditorChannelDelta<T>& update
) {
    if (mesh_editor_channel_delta_empty(update)) {
        return true;
    }
    if (mesh_editor_channel_delta_empty(target)) {
        target = update;
        return true;
    }
    if (target.replacement || update.replacement || target.after_size != update.before_size) {
        return false;
    }
    std::map<int, std::size_t> positions;
    for (std::size_t position = 0; position < target.indices.size(); ++position) {
        positions[target.indices[position]] = position;
    }
    for (std::size_t position = 0; position < update.indices.size(); ++position) {
        const int index = update.indices[position];
        const auto found = positions.find(index);
        if (found == positions.end()) {
            positions[index] = target.indices.size();
            target.indices.push_back(index);
            target.before_values.push_back(update.before_values[position]);
            target.after_values.push_back(update.after_values[position]);
        } else {
            target.after_values[found->second] = update.after_values[position];
        }
    }
    target.after_size = update.after_size;
    return true;
}

bool mesh_editor_can_merge_submesh_delta(
    const MeshEditorSubmeshDelta& target,
    const MeshEditorSubmeshDelta& update
) {
    return mesh_editor_can_merge_channel_delta(target.vertices, update.vertices)
        && mesh_editor_can_merge_channel_delta(target.faces, update.faces)
        && mesh_editor_can_merge_channel_delta(target.source_face_indices, update.source_face_indices)
        && mesh_editor_can_merge_channel_delta(target.normals, update.normals)
        && mesh_editor_can_merge_channel_delta(target.uvs, update.uvs)
        && mesh_editor_can_merge_channel_delta(target.tangents, update.tangents)
        && mesh_editor_can_merge_channel_delta(target.tangent_signs, update.tangent_signs)
        && mesh_editor_can_merge_channel_delta(target.bone_indices, update.bone_indices)
        && mesh_editor_can_merge_channel_delta(target.bone_weights, update.bone_weights)
        && mesh_editor_can_merge_channel_delta(target.source_vertex_map, update.source_vertex_map)
        && mesh_editor_can_merge_channel_delta(target.source_vertex_offsets, update.source_vertex_offsets);
}

MeshEditorPreEditChannels mesh_editor_capture_pre_edit_channels(
    const MeshSessionSubmesh& submesh,
    bool capture_faces,
    bool capture_normals,
    bool capture_uvs,
    bool capture_tangents,
    bool capture_metadata
) {
    MeshEditorPreEditChannels captured;
    captured.capture_faces = capture_faces;
    captured.capture_normals = capture_normals;
    captured.capture_uvs = capture_uvs;
    captured.capture_tangents = capture_tangents;
    captured.capture_metadata = capture_metadata;
    if (capture_faces) captured.faces = submesh.faces;
    if (capture_normals) captured.normals = submesh.normals;
    if (capture_uvs) captured.uvs = submesh.uvs;
    if (capture_tangents) {
        captured.tangents = submesh.tangents;
        captured.tangent_signs = submesh.tangent_signs;
    }
    if (capture_metadata) {
        captured.name = submesh.name;
        captured.material = submesh.material;
        captured.texture = submesh.texture;
        captured.extra_attrs = submesh.extra_attrs;
    }
    return captured;
}

void mesh_editor_finish_pre_edit_channels(
    MeshEditorSubmeshDelta& delta,
    const MeshEditorPreEditChannels& captured,
    const MeshSessionSubmesh& after
) {
    if (captured.capture_faces) delta.faces = mesh_editor_make_channel_delta(captured.faces, after.faces);
    if (captured.capture_normals) delta.normals = mesh_editor_make_channel_delta(captured.normals, after.normals);
    if (captured.capture_uvs) delta.uvs = mesh_editor_make_channel_delta(captured.uvs, after.uvs);
    if (captured.capture_tangents) {
        delta.tangents = mesh_editor_make_channel_delta(captured.tangents, after.tangents);
        delta.tangent_signs = mesh_editor_make_channel_delta(captured.tangent_signs, after.tangent_signs);
    }
    if (captured.capture_metadata) {
        delta.metadata_changed = captured.name != after.name
            || captured.material != after.material
            || captured.texture != after.texture
            || !mesh_editor_extra_attrs_equal(captured.extra_attrs, after.extra_attrs);
        if (delta.metadata_changed) {
            delta.before_name = captured.name;
            delta.after_name = after.name;
            delta.before_material = captured.material;
            delta.after_material = after.material;
            delta.before_texture = captured.texture;
            delta.after_texture = after.texture;
            delta.before_extra_attrs = captured.extra_attrs;
            delta.after_extra_attrs = after.extra_attrs;
        }
    }
}

bool mesh_editor_add_sparse_position_result(
    MeshEditorSubmeshDelta& delta,
    const SubmeshMeshEditResult& result,
    const MeshSessionSubmesh& after
) {
    if (result.changed_vertices.empty()) {
        return true;
    }
    if (result.before_positions.size() != result.changed_vertices.size()) {
        return false;
    }
    MeshEditorChannelDelta<Vec3> update;
    update.before_size = after.vertices.size();
    update.after_size = after.vertices.size();
    for (std::size_t position = 0; position < result.changed_vertices.size(); ++position) {
        const int vertex_index = result.changed_vertices[position];
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= after.vertices.size()) {
            return false;
        }
        update.indices.push_back(vertex_index);
        update.before_values.push_back(result.before_positions[position]);
        update.after_values.push_back(after.vertices[static_cast<std::size_t>(vertex_index)]);
    }
    return mesh_editor_merge_channel_delta(delta.vertices, update);
}

SubmeshMeshEditResult mesh_editor_sparse_position_history_result(
    int submesh_index,
    const MeshSessionSubmesh& restored,
    const MeshEditorSubmeshDelta& delta,
    std::vector<Vec3> before_positions,
    const std::string& operation,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshMeshEditResult result;
    result.index = submesh_index;
    result.action = operation;
    result.sparse = true;
    result.changed_vertices = delta.vertices.indices;
    result.before_positions = std::move(before_positions);
    result.changed_positions.reserve(result.changed_vertices.size());
    result.changed_source_vertex_ids.reserve(result.changed_vertices.size());
    for (const int vertex_index : result.changed_vertices) {
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= restored.vertices.size()) {
            continue;
        }
        result.changed_positions.push_back(restored.vertices[static_cast<std::size_t>(vertex_index)]);
        result.changed_source_vertex_ids.push_back(
            restored.source_vertex_map.size() == restored.vertices.size()
                ? restored.source_vertex_map[static_cast<std::size_t>(vertex_index)]
                : vertex_index
        );
    }
    mesh_editor_set_result_output_paths(result, delta_output_dir, session_id);
    return result;
}

bool mesh_editor_submesh_delta_empty(const MeshEditorSubmeshDelta& delta) {
    return mesh_editor_channel_delta_empty(delta.vertices)
        && mesh_editor_channel_delta_empty(delta.faces)
        && mesh_editor_channel_delta_empty(delta.source_face_indices)
        && mesh_editor_channel_delta_empty(delta.normals)
        && mesh_editor_channel_delta_empty(delta.uvs)
        && mesh_editor_channel_delta_empty(delta.tangents)
        && mesh_editor_channel_delta_empty(delta.tangent_signs)
        && mesh_editor_channel_delta_empty(delta.bone_indices)
        && mesh_editor_channel_delta_empty(delta.bone_weights)
        && mesh_editor_channel_delta_empty(delta.source_vertex_map)
        && mesh_editor_channel_delta_empty(delta.source_vertex_offsets)
        && !delta.metadata_changed;
}

void mesh_editor_apply_submesh_delta(
    MeshSessionSubmesh& target,
    const MeshEditorSubmeshDelta& delta,
    bool restore_before
) {
    mesh_editor_apply_channel_delta(target.vertices, delta.vertices, restore_before);
    mesh_editor_apply_channel_delta(target.faces, delta.faces, restore_before);
    mesh_editor_apply_channel_delta(target.source_face_indices, delta.source_face_indices, restore_before);
    mesh_editor_apply_channel_delta(target.normals, delta.normals, restore_before);
    mesh_editor_apply_channel_delta(target.uvs, delta.uvs, restore_before);
    mesh_editor_apply_channel_delta(target.tangents, delta.tangents, restore_before);
    mesh_editor_apply_channel_delta(target.tangent_signs, delta.tangent_signs, restore_before);
    mesh_editor_apply_channel_delta(target.bone_indices, delta.bone_indices, restore_before);
    mesh_editor_apply_channel_delta(target.bone_weights, delta.bone_weights, restore_before);
    mesh_editor_apply_channel_delta(target.source_vertex_map, delta.source_vertex_map, restore_before);
    mesh_editor_apply_channel_delta(target.source_vertex_offsets, delta.source_vertex_offsets, restore_before);
    if (delta.metadata_changed) {
        target.name = restore_before ? delta.before_name : delta.after_name;
        target.material = restore_before ? delta.before_material : delta.after_material;
        target.texture = restore_before ? delta.before_texture : delta.after_texture;
        target.extra_attrs = restore_before ? delta.before_extra_attrs : delta.after_extra_attrs;
    }
}

bool mesh_editor_merge_submesh_delta(MeshEditorSubmeshDelta& target, const MeshEditorSubmeshDelta& update) {
    if (!mesh_editor_merge_channel_delta(target.vertices, update.vertices)
        || !mesh_editor_merge_channel_delta(target.faces, update.faces)
        || !mesh_editor_merge_channel_delta(target.source_face_indices, update.source_face_indices)
        || !mesh_editor_merge_channel_delta(target.normals, update.normals)
        || !mesh_editor_merge_channel_delta(target.uvs, update.uvs)
        || !mesh_editor_merge_channel_delta(target.tangents, update.tangents)
        || !mesh_editor_merge_channel_delta(target.tangent_signs, update.tangent_signs)
        || !mesh_editor_merge_channel_delta(target.bone_indices, update.bone_indices)
        || !mesh_editor_merge_channel_delta(target.bone_weights, update.bone_weights)
        || !mesh_editor_merge_channel_delta(target.source_vertex_map, update.source_vertex_map)
        || !mesh_editor_merge_channel_delta(target.source_vertex_offsets, update.source_vertex_offsets)) {
        return false;
    }
    if (update.metadata_changed) {
        if (!target.metadata_changed) {
            target.before_name = update.before_name;
            target.before_material = update.before_material;
            target.before_texture = update.before_texture;
            target.before_extra_attrs = update.before_extra_attrs;
        }
        target.after_name = update.after_name;
        target.after_material = update.after_material;
        target.after_texture = update.after_texture;
        target.after_extra_attrs = update.after_extra_attrs;
        target.metadata_changed = true;
    }
    return true;
}

void mesh_editor_set_material_result_metadata(SubmeshMeshEditResult& result, const MeshSessionSubmesh& submesh) {
    result.name = submesh.name;
    result.material = submesh.material;
    result.texture = submesh.texture;
    result.extra_attrs = mesh_editor_extra_attrs_object(submesh);
    result.material_metadata_changed = true;
}

void mesh_editor_set_result_preview_geometry(SubmeshMeshEditResult& result, const MeshSessionSubmesh& submesh) {
    result.vertices = submesh.vertices;
    result.faces = submesh.faces;
    result.normals = submesh.normals;
    result.preview_uvs = submesh.uvs;
    result.source_vertex_map = submesh.source_vertex_map;
    result.source_face_indices = submesh.source_face_indices;
}

std::set<int> mesh_editor_material_candidate_indices(const MeshEditorSession& session) {
    std::set<int> candidates = session.selection.source_indices;
    for (const auto& entry : session.selection.vertices) {
        candidates.insert(entry.first);
    }
    for (const auto& entry : session.selection.edges) {
        candidates.insert(entry.first);
    }
    for (const auto& entry : session.selection.faces) {
        candidates.insert(entry.first);
    }
    for (auto iter = candidates.begin(); iter != candidates.end();) {
        if (mesh_editor_submeshes(session).find(*iter) == mesh_editor_submeshes(session).end()) {
            iter = candidates.erase(iter);
        } else {
            ++iter;
        }
    }
    return candidates;
}

bool mesh_editor_material_has_component_selection(const MeshEditorSession& session) {
    return !session.selection.vertices.empty() || !session.selection.edges.empty() || !session.selection.faces.empty();
}

const JsonValue* mesh_editor_submesh_item_from_root(const JsonValue& root, int submesh_index) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        return nullptr;
    }
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type == JsonValue::Type::Object && int_or(item.get("index"), -1) == submesh_index) {
            return &item;
        }
    }
    return nullptr;
}

std::vector<SubmeshMeshEditResult> run_mesh_editor_material_edit(
    const MeshEditorSession& session,
    const JsonValue& edit_root,
    const JsonValue& edit,
    const std::string& operation
) {
    std::vector<SubmeshMeshEditResult> results;
    if (operation == "material_assign" && !mesh_editor_material_assign_has_payload(edit)) {
        return results;
    }
    int source_index = -1;
    MeshSessionSubmesh source_material;
    if (operation == "material_copy") {
        const JsonValue* source_value = edit.get("source_submesh_index");
        if (source_value == nullptr) {
            source_value = edit.get("source_index");
        }
        if (source_value == nullptr || !strict_int_or(source_value, source_index)) {
            return results;
        }
        const auto source_found = mesh_editor_submeshes(session).find(source_index);
        if (source_index < 0 || source_found == mesh_editor_submeshes(session).end()) {
            return results;
        }
        source_material = source_found->second;
    }

    const std::set<int> candidates = mesh_editor_material_candidate_indices(session);
    if (candidates.empty()) {
        return results;
    }
    const bool has_component_selection = mesh_editor_material_has_component_selection(session);
    for (const int target_index : candidates) {
        const auto target_found = mesh_editor_submeshes(session).find(target_index);
        if (target_found == mesh_editor_submeshes(session).end()) {
            continue;
        }
        if (operation == "material_copy" && target_index == source_index) {
            continue;
        }
        MeshSessionSubmesh updated = target_found->second;
        if (operation == "material_assign") {
            mesh_editor_apply_material_assign(updated, edit);
        } else {
            mesh_editor_apply_material_copy(updated, source_material, source_index);
        }
        if (mesh_editor_same_material_metadata(target_found->second, updated)) {
            continue;
        }

        const bool source_selected = session.selection.source_indices.find(target_index) != session.selection.source_indices.end();
        const JsonValue* item = mesh_editor_submesh_item_from_root(edit_root, target_index);
        std::set<int> selected_faces;
        if (item != nullptr && !source_selected) {
            const std::vector<Vec3> vertices = mesh_vertices_from_item(*item);
            const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(*item, vertices.size());
            selected_faces = selected_faces_from_topology_json(*item, faces, vertices.size());
            if (has_component_selection && selected_faces.empty()) {
                continue;
            }
            if (!selected_faces.empty() && selected_faces.size() < faces.size()) {
                std::vector<SubmeshMeshEditResult> split_results = run_separate_edit_for_submesh(*item);
                if (split_results.size() != 2) {
                    continue;
                }
                MeshSessionSubmesh source_after = mesh_editor_submesh_from_result(split_results[0]);
                source_after.name = target_found->second.name;
                source_after.material = target_found->second.material;
                source_after.texture = target_found->second.texture;
                source_after.extra_attrs = target_found->second.extra_attrs;
                split_results[0].action = operation;
                split_results[0].name = source_after.name;
                split_results[0].material = source_after.material;
                split_results[0].texture = source_after.texture;
                split_results[0].extra_attrs = source_after.extra_attrs;

                split_results[1].action = operation;
                split_results[1].name_suffix = " material";
                MeshSessionSubmesh append_after = mesh_editor_submesh_from_result(split_results[1]);
                const std::string base_name = target_found->second.name.empty()
                    ? (target_found->second.material.empty() ? std::string("part_") + std::to_string(target_index) : target_found->second.material)
                    : target_found->second.name;
                append_after.name = base_name + split_results[1].name_suffix;
                append_after.material = target_found->second.material;
                append_after.texture = target_found->second.texture;
                append_after.extra_attrs = target_found->second.extra_attrs;
                if (operation == "material_assign") {
                    mesh_editor_apply_material_assign(append_after, edit);
                } else {
                    mesh_editor_apply_material_copy(append_after, source_material, source_index);
                }
                mesh_editor_set_material_result_metadata(split_results[1], append_after);
                results.push_back(std::move(split_results[0]));
                results.push_back(std::move(split_results[1]));
                continue;
            }
        }

        SubmeshMeshEditResult result;
        result.index = target_index;
        result.action = operation;
        mesh_editor_set_material_result_metadata(result, updated);
        mesh_editor_set_result_preview_geometry(result, updated);
        results.push_back(std::move(result));
    }
    return results;
}

SubmeshMeshEditResult mesh_editor_result_from_cleanup_result(
    const SubmeshCleanupResult& source,
    const std::string& action
) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = action;
    result.vertices = source.vertices;
    result.faces = source.faces;
    result.normals = source.normals;
    result.preview_uvs = source.uvs;
    result.tangents = source.tangents;
    result.tangent_signs = source.tangent_signs;
    result.bones = source.bones;
    result.source_vertex_map = source.source_vertex_map;
    result.source_vertex_offsets = source.source_vertex_offsets;
    result.source_face_indices = identity_indices(source.faces.size());
    result.index_map = source.index_map;
    result.copy_vertex_indices.assign(source.vertices.size(), -1);
    for (std::size_t old_index = 0; old_index < source.index_map.size(); ++old_index) {
        const int new_index = source.index_map[old_index];
        if (new_index >= 0 && static_cast<std::size_t>(new_index) < result.copy_vertex_indices.size()) {
            result.copy_vertex_indices[static_cast<std::size_t>(new_index)] = static_cast<int>(old_index);
        }
    }
    result.removed_vertices = source.removed_vertices;
    result.removed_faces = source.removed_faces;
    result.topology_changed = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_cleanup_results(
    const std::vector<SubmeshCleanupResult>& sources,
    const std::string& action
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshCleanupResult& source : sources) {
        if (source.index >= 0 && (!source.vertices.empty() || !source.faces.empty())) {
            results.push_back(mesh_editor_result_from_cleanup_result(source, action));
        }
    }
    return results;
}
