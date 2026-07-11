MeshEditorSelection mesh_editor_selection_from_json(const JsonValue* raw_selection, const MeshEditorSession* session = nullptr) {
    MeshEditorSelection selection;
    if (raw_selection == nullptr || raw_selection->type != JsonValue::Type::Object) {
        return selection;
    }
    const JsonValue* raw_brush = raw_selection->get("screen_brush");
    const JsonValue* raw_region = raw_selection->get("screen_region");
    const bool projected_screen_selection =
        mesh_editor_has_projection_payload(raw_brush, -1)
        || mesh_editor_has_projection_payload(raw_region, -1);
    if (!projected_screen_selection) {
        mesh_editor_read_index_groups(raw_selection->get("vertices_by_submesh"), "vertices", selection.vertices);
        mesh_editor_read_vertex_weight_groups(raw_selection->get("vertices_by_submesh"), selection.vertex_weights);
        mesh_editor_read_index_groups(raw_selection->get("faces_by_submesh"), "faces", selection.faces);
        mesh_editor_read_edge_groups(raw_selection->get("edges_by_submesh"), selection.edges);
        selection.source_indices = mesh_editor_indices_from_json(raw_selection->get("source_indices"));

        const int submesh_index = int_or(raw_selection->get("submesh_index"), -1);
        if (submesh_index >= 0) {
            const std::set<int> vertices = mesh_editor_indices_from_json(raw_selection->get("vertices"));
            const std::set<int> faces = mesh_editor_indices_from_json(raw_selection->get("faces"));
            const std::set<std::array<int, 2>> edges = mesh_editor_edges_from_json(raw_selection->get("edges"));
            if (!vertices.empty()) selection.vertices[submesh_index] = vertices;
            if (!faces.empty()) selection.faces[submesh_index] = faces;
            if (!edges.empty()) selection.edges[submesh_index] = edges;
        }
    }
    mesh_editor_add_screen_brush_selection(session, raw_selection, selection);
    mesh_editor_add_screen_region_selection(session, raw_selection, selection);
    mesh_editor_prune_vertex_weights_to_selection(selection);
    return selection;
}

std::size_t mesh_editor_selected_vertex_count(const MeshEditorSelection& selection) {
    std::size_t count = 0;
    for (const auto& entry : selection.vertices) {
        count += entry.second.size();
    }
    return count;
}

std::size_t mesh_editor_selected_edge_count(const MeshEditorSelection& selection) {
    std::size_t count = 0;
    for (const auto& entry : selection.edges) {
        count += entry.second.size();
    }
    return count;
}

std::size_t mesh_editor_selected_face_count(const MeshEditorSelection& selection) {
    std::size_t count = 0;
    for (const auto& entry : selection.faces) {
        count += entry.second.size();
    }
    return count;
}

bool mesh_editor_selection_empty(const MeshEditorSelection& selection) {
    return selection.source_indices.empty()
        && mesh_editor_selected_vertex_count(selection) == 0
        && mesh_editor_selected_edge_count(selection) == 0
        && mesh_editor_selected_face_count(selection) == 0;
}

bool mesh_editor_is_live_stroke_operation(const std::string& operation) {
    return operation == "brush" || operation == "transform";
}

std::string mesh_editor_stroke_phase_from_json(const JsonValue& root, const JsonValue& edit) {
    std::string phase = lower_ascii(string_or(edit.get("stroke_phase"), string_or(root.get("stroke_phase"), "")));
    if (phase == "finish") {
        return "end";
    }
    return phase;
}

bool mesh_editor_valid_stroke_phase(const std::string& phase) {
    return phase.empty() || phase == "begin" || phase == "update" || phase == "end" || phase == "cancel";
}

std::string mesh_editor_stroke_id_from_json(const JsonValue& root, const JsonValue& edit) {
    return string_or(edit.get("stroke_id"), string_or(root.get("stroke_id"), ""));
}

std::string mesh_editor_tool_from_edit(const JsonValue& edit) {
    return lower_ascii(string_or(edit.get("tool"), string_or(edit.get("mode"), "")));
}

void mesh_editor_write_metrics(std::ostream& out, double cpp_ms, double io_serialization_ms = 0.0) {
    out << "\"metrics\":{\"cpp_ms\":" << cpp_ms
        << ",\"io_serialization_ms\":" << io_serialization_ms
        << ",\"python_apply_ms\":0,\"d3d11_update_ms\":0}";
}

void mesh_editor_write_session_counts(std::ostream& out, const MeshEditorSession& session) {
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    for (const auto& entry : mesh_editor_submeshes(session)) {
        vertex_count += entry.second.vertices.size();
        face_count += entry.second.faces.size();
    }
    const std::size_t undo_bytes = mesh_editor_history_stack_retained_bytes(session.undo_stack);
    const std::size_t redo_bytes = mesh_editor_history_stack_retained_bytes(session.redo_stack);
    out << "\"submesh_count\":" << mesh_editor_submeshes(session).size()
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"topology_revision\":" << session.topology_revision
        << ",\"selection_revision\":" << session.selection_revision
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"stroke_revision\":" << session.stroke_revision
        << ",\"active_stroke\":" << (session.active_stroke.active ? "true" : "false")
        << ",\"history_undo_count\":" << session.undo_stack.size()
        << ",\"history_redo_count\":" << session.redo_stack.size()
        << ",\"history_undo_retained_bytes\":" << undo_bytes
        << ",\"history_redo_retained_bytes\":" << redo_bytes
        << ",\"history_retained_bytes\":" << (undo_bytes + redo_bytes)
        << ",\"history_max_operations\":" << MESH_EDITOR_HISTORY_MAX_OPERATIONS
        << ",\"history_max_bytes\":" << MESH_EDITOR_HISTORY_MAX_BYTES
        << ",\"selected_vertex_count\":" << mesh_editor_selected_vertex_count(session.selection)
        << ",\"selected_edge_count\":" << mesh_editor_selected_edge_count(session.selection)
        << ",\"selected_face_count\":" << mesh_editor_selected_face_count(session.selection);
}

void mesh_editor_write_extra_attrs_field(std::ostream& out, const JsonValue& extra_attrs) {
    if (extra_attrs.type != JsonValue::Type::Object || extra_attrs.object_value.empty()) {
        return;
    }
    out << ",\"extra_attrs\":";
    write_json_value(out, extra_attrs);
}

void mesh_editor_write_submesh_summaries(std::ostream& out, const MeshEditorSession& session) {
    out << "\"submeshes\":[";
    bool wrote = false;
    for (const auto& entry : mesh_editor_submeshes(session)) {
        if (wrote) {
            out << ',';
        }
        wrote = true;
        const auto selected_sources = session.selection.source_indices.find(entry.first);
        const auto selected_vertices = session.selection.vertices.find(entry.first);
        const auto selected_edges = session.selection.edges.find(entry.first);
        const auto selected_faces = session.selection.faces.find(entry.first);
        out << "{\"index\":" << entry.first
            << ",\"name\":";
        write_escaped(out, entry.second.name);
        out << ",\"material\":";
        write_escaped(out, entry.second.material);
        out << ",\"texture\":";
        write_escaped(out, entry.second.texture);
        mesh_editor_write_extra_attrs_field(out, entry.second.extra_attrs);
        out
            << ",\"vertex_count\":" << entry.second.vertices.size()
            << ",\"face_count\":" << entry.second.faces.size()
            << ",\"uv_count\":" << entry.second.uvs.size()
            << ",\"normal_count\":" << entry.second.normals.size()
            << ",\"tangent_count\":" << entry.second.tangents.size()
            << ",\"selected\":" << (
                selected_sources != session.selection.source_indices.end()
                || selected_vertices != session.selection.vertices.end()
                || selected_edges != session.selection.edges.end()
                || selected_faces != session.selection.faces.end()
                ? "true" : "false"
            )
            << ",\"selected_vertex_count\":" << (
                selected_vertices == session.selection.vertices.end()
                    ? 0
                    : selected_vertices->second.size()
            )
            << ",\"selected_edge_count\":" << (
                selected_edges == session.selection.edges.end()
                    ? 0
                    : selected_edges->second.size()
            )
            << ",\"selected_face_count\":" << (
                selected_faces == session.selection.faces.end()
                    ? 0
                    : selected_faces->second.size()
            )
            << ",\"has_skinning\":" << (
                (!entry.second.bone_indices.empty() || !entry.second.bone_weights.empty()) ? "true" : "false"
            )
            << "}";
    }
    out << "]";
}

const JsonValue* mesh_editor_value_for_submesh(const JsonValue* value, int submesh_index);

JsonValue mesh_editor_apply_root_json(
    const std::string& editor_session_id,
    const std::string& native_session_id,
    const MeshEditorSession& session,
    const JsonValue& edit,
    const std::string& delta_output_dir
) {
    JsonValue root;
    root.type = JsonValue::Type::Object;
    root.object_value["edit"] = edit;
    const JsonValue* mirror_pairs_by_submesh = edit.get("mirror_pairs_by_submesh");
    const JsonValue* source_normals_by_submesh = edit.get("source_normals_by_submesh");

    JsonValue submeshes;
    submeshes.type = JsonValue::Type::Array;
    for (const auto& entry : mesh_editor_submeshes(session)) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        item.object_value["index"] = mesh_editor_json_number(entry.first);
        item.object_value["session_id"] = mesh_editor_json_string(native_session_id);
        item.object_value["editor_session_id"] = mesh_editor_json_string(editor_session_id);
        item.object_value["sparse_output"] = mesh_editor_json_bool(true);
        if (session.selection.source_indices.find(entry.first) != session.selection.source_indices.end()) {
            item.object_value["selected_all_vertices"] = mesh_editor_json_bool(true);
            item.object_value["selected_all_faces"] = mesh_editor_json_bool(true);
        }
        if (const JsonValue* mirror_pairs = mesh_editor_value_for_submesh(mirror_pairs_by_submesh, entry.first)) {
            item.object_value["mirror_pairs"] = *mirror_pairs;
        }
        if (const JsonValue* source_normals = mesh_editor_value_for_submesh(source_normals_by_submesh, entry.first)) {
            item.object_value["source_normals_binary"] = *source_normals;
        }
        mesh_editor_add_delta_output_paths(item, delta_output_dir, editor_session_id, entry.first);
        submeshes.array_value.push_back(item);
    }
    root.object_value["submeshes"] = submeshes;
    return root;
}

const JsonValue* mesh_editor_value_for_submesh(const JsonValue* value, int submesh_index) {
    if (value == nullptr) {
        return nullptr;
    }
    if (value->type == JsonValue::Type::Object) {
        return value->get(std::to_string(submesh_index));
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index == submesh_index) {
                const JsonValue* values = item.get("values");
                return values != nullptr ? values : &item;
            }
        }
    }
    return nullptr;
}

bool mesh_editor_item_targets_normal_operation(const JsonValue& item, const std::string& operation) {
    const int index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    if (index < 0 || vertices.empty()) {
        return false;
    }
    if (operation == "copy_normals") {
        return !selected_vertices_from_edit_domains(item, vertices.size(), faces).empty();
    }
    if (faces.empty()) {
        return false;
    }
    return !selected_faces_from_topology_json(item, faces, vertices.size()).empty();
}

JsonValue mesh_editor_filter_root_to_selected_normal_targets(const JsonValue& root, const std::string& operation) {
    JsonValue filtered_root = root;
    JsonValue filtered_submeshes;
    filtered_submeshes.type = JsonValue::Type::Array;
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes != nullptr && submeshes->type == JsonValue::Type::Array) {
        for (const JsonValue& item : submeshes->array_value) {
            if (item.type == JsonValue::Type::Object && mesh_editor_item_targets_normal_operation(item, operation)) {
                filtered_submeshes.array_value.push_back(item);
            }
        }
    }
    filtered_root.object_value["submeshes"] = std::move(filtered_submeshes);
    return filtered_root;
}

std::size_t mesh_editor_json_retained_bytes(const JsonValue& value) {
    std::size_t retained = sizeof(JsonValue) + value.string_value.capacity();
    retained += value.array_value.capacity() * sizeof(JsonValue);
    for (const JsonValue& item : value.array_value) {
        retained += mesh_editor_json_retained_bytes(item);
    }
    for (const auto& item : value.object_value) {
        retained += sizeof(item) + item.first.capacity() + mesh_editor_json_retained_bytes(item.second);
    }
    return retained;
}

template <typename T>
std::size_t mesh_editor_channel_delta_retained_bytes(const MeshEditorChannelDelta<T>& delta) {
    std::size_t retained = 0;
    retained += delta.indices.capacity() * sizeof(int);
    retained += (delta.before_values.capacity() + delta.after_values.capacity()) * sizeof(T);
    retained += (delta.before_replacement.capacity() + delta.after_replacement.capacity()) * sizeof(T);
    if constexpr (std::is_same_v<T, std::vector<int>>) {
        for (const auto& values : delta.before_values) retained += values.capacity() * sizeof(int);
        for (const auto& values : delta.after_values) retained += values.capacity() * sizeof(int);
        for (const auto& values : delta.before_replacement) retained += values.capacity() * sizeof(int);
        for (const auto& values : delta.after_replacement) retained += values.capacity() * sizeof(int);
    } else if constexpr (std::is_same_v<T, std::vector<double>>) {
        for (const auto& values : delta.before_values) retained += values.capacity() * sizeof(double);
        for (const auto& values : delta.after_values) retained += values.capacity() * sizeof(double);
        for (const auto& values : delta.before_replacement) retained += values.capacity() * sizeof(double);
        for (const auto& values : delta.after_replacement) retained += values.capacity() * sizeof(double);
    }
    return retained;
}

std::size_t mesh_editor_submesh_retained_bytes(const MeshSessionSubmesh& submesh) {
    std::size_t retained = sizeof(submesh) + submesh.name.capacity() + submesh.material.capacity() + submesh.texture.capacity();
    retained += submesh.vertices.capacity() * sizeof(Vec3);
    retained += submesh.faces.capacity() * sizeof(std::array<int, 3>);
    retained += submesh.source_face_indices.capacity() * sizeof(int);
    retained += submesh.normals.capacity() * sizeof(Vec3);
    retained += submesh.uvs.capacity() * sizeof(Vec2);
    retained += submesh.tangents.capacity() * sizeof(Vec3);
    retained += submesh.tangent_signs.capacity() * sizeof(double);
    retained += submesh.source_vertex_map.capacity() * sizeof(int);
    retained += submesh.source_vertex_offsets.capacity() * sizeof(int);
    for (const auto& values : submesh.bone_indices) retained += sizeof(values) + values.capacity() * sizeof(int);
    for (const auto& values : submesh.bone_weights) retained += sizeof(values) + values.capacity() * sizeof(double);
    retained += mesh_editor_json_retained_bytes(submesh.extra_attrs);
    return retained;
}

std::size_t mesh_editor_submesh_delta_retained_bytes(const MeshEditorSubmeshDelta& delta) {
    return sizeof(delta)
        + mesh_editor_channel_delta_retained_bytes(delta.vertices)
        + mesh_editor_channel_delta_retained_bytes(delta.faces)
        + mesh_editor_channel_delta_retained_bytes(delta.source_face_indices)
        + mesh_editor_channel_delta_retained_bytes(delta.normals)
        + mesh_editor_channel_delta_retained_bytes(delta.uvs)
        + mesh_editor_channel_delta_retained_bytes(delta.tangents)
        + mesh_editor_channel_delta_retained_bytes(delta.tangent_signs)
        + mesh_editor_channel_delta_retained_bytes(delta.bone_indices)
        + mesh_editor_channel_delta_retained_bytes(delta.bone_weights)
        + mesh_editor_channel_delta_retained_bytes(delta.source_vertex_map)
        + mesh_editor_channel_delta_retained_bytes(delta.source_vertex_offsets)
        + delta.before_name.capacity() + delta.after_name.capacity()
        + delta.before_material.capacity() + delta.after_material.capacity()
        + delta.before_texture.capacity() + delta.after_texture.capacity()
        + mesh_editor_json_retained_bytes(delta.before_extra_attrs)
        + mesh_editor_json_retained_bytes(delta.after_extra_attrs);
}

std::size_t mesh_editor_history_entry_retained_bytes(const MeshEditorHistoryEntry& entry) {
    std::size_t retained = sizeof(entry) + entry.operation.capacity() + entry.stroke_id.capacity();
    for (const auto& item : entry.before) retained += sizeof(item) + mesh_editor_submesh_retained_bytes(item.second);
    for (const auto& item : entry.deltas) retained += sizeof(item) + mesh_editor_submesh_delta_retained_bytes(item.second);
    retained += entry.absent_before.size() * (sizeof(int) + 3 * sizeof(void*));
    retained += entry.append_source_indices.size() * (2 * sizeof(int) + 3 * sizeof(void*));
    return retained;
}

std::size_t mesh_editor_history_stack_retained_bytes(const std::vector<MeshEditorHistoryEntry>& stack) {
    std::size_t retained = stack.capacity() * sizeof(MeshEditorHistoryEntry);
    for (const MeshEditorHistoryEntry& entry : stack) retained += mesh_editor_history_entry_retained_bytes(entry);
    return retained;
}

void mesh_editor_trim_history(std::vector<MeshEditorHistoryEntry>& stack) {
    while (!stack.empty()
        && (stack.size() > MESH_EDITOR_HISTORY_MAX_OPERATIONS
            || mesh_editor_history_stack_retained_bytes(stack) > MESH_EDITOR_HISTORY_MAX_BYTES)) {
        stack.erase(stack.begin());
    }
}

void mesh_editor_push_history(std::vector<MeshEditorHistoryEntry>& stack, MeshEditorHistoryEntry entry) {
    stack.push_back(std::move(entry));
    mesh_editor_trim_history(stack);
}

void mesh_editor_trim_session_history(MeshEditorSession& session) {
    while ((!session.undo_stack.empty() || !session.redo_stack.empty())
        && (session.undo_stack.size() + session.redo_stack.size() > MESH_EDITOR_HISTORY_MAX_OPERATIONS
            || mesh_editor_history_stack_retained_bytes(session.undo_stack)
                + mesh_editor_history_stack_retained_bytes(session.redo_stack) > MESH_EDITOR_HISTORY_MAX_BYTES)) {
        if (!session.undo_stack.empty()) {
            session.undo_stack.erase(session.undo_stack.begin());
        } else {
            session.redo_stack.erase(session.redo_stack.begin());
        }
    }
}

void mesh_editor_restore_submeshes(
    MeshEditorSession& session,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    for (const auto& entry : submeshes) {
        mesh_editor_submeshes(session)[entry.first] = entry.second;
    }
}

int mesh_editor_next_submesh_index(const MeshEditorSession& session) {
    int next_index = 0;
    for (const auto& entry : mesh_editor_submeshes(session)) {
        next_index = std::max(next_index, entry.first + 1);
    }
    return next_index;
}

MeshSessionSubmesh mesh_editor_submesh_from_result(const SubmeshMeshEditResult& result) {
    MeshSessionSubmesh submesh;
    submesh.name = result.name;
    submesh.material = result.material;
    submesh.texture = result.texture;
    submesh.extra_attrs = result.extra_attrs;
    submesh.vertices = result.vertices;
    submesh.faces = result.faces;
    submesh.source_face_indices = result.source_face_indices.size() == result.faces.size()
        ? result.source_face_indices
        : identity_indices(result.faces.size());
    submesh.normals = result.normals.size() == result.vertices.size() ? result.normals : std::vector<Vec3>();
    submesh.uvs = result.preview_uvs.size() == result.vertices.size() ? result.preview_uvs : std::vector<Vec2>();
    submesh.tangents = result.tangents.size() == result.vertices.size() ? result.tangents : std::vector<Vec3>();
    submesh.tangent_signs = result.tangent_signs.size() == result.vertices.size() ? result.tangent_signs : std::vector<double>();
    if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
        submesh.bone_indices = result.bones.indices;
        submesh.bone_weights = result.bones.weights;
    }
    submesh.source_vertex_map = result.source_vertex_map.size() == result.vertices.size() ? result.source_vertex_map : std::vector<int>();
    submesh.source_vertex_offsets = result.source_vertex_offsets.size() == result.vertices.size() ? result.source_vertex_offsets : std::vector<int>();
    return submesh;
}

SubmeshMeshEditResult mesh_editor_result_from_transform_result(const SubmeshTransformResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "transform";
    result.changed_vertices = source.changed_vertices;
    result.changed_positions = source.changed_positions;
    result.before_positions = source.before_positions;
    result.sparse_snapshot_id = source.sparse_snapshot_id;
    result.changed_vertices_path = source.changed_vertices_path;
    result.changed_positions_path = source.changed_positions_path;
    result.before_positions_path = source.before_positions_path;
    result.source_vertex_map = source.source_vertex_map;
    result.changed_source_vertex_ids = source.changed_source_vertex_ids;
    result.sparse = true;
    result.resident_sparse = source.resident_sparse;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_transform_results(
    const std::vector<SubmeshTransformResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshTransformResult& source : sources) {
        results.push_back(mesh_editor_result_from_transform_result(source));
    }
    return results;
}

std::string mesh_editor_compact_json(const JsonValue& value) {
    std::ostringstream out;
    write_json_value(out, value);
    return out.str();
}

JsonValue mesh_editor_json_object() {
    JsonValue value;
    value.type = JsonValue::Type::Object;
    return value;
}

bool mesh_editor_json_object_empty(const JsonValue& value) {
    return value.type != JsonValue::Type::Object || value.object_value.empty();
}

JsonValue mesh_editor_extra_attrs_object(const MeshSessionSubmesh& submesh) {
    return submesh.extra_attrs.type == JsonValue::Type::Object ? submesh.extra_attrs : mesh_editor_json_object();
}

bool mesh_editor_extra_attrs_equal(const JsonValue& left, const JsonValue& right) {
    return mesh_editor_compact_json(left.type == JsonValue::Type::Object ? left : mesh_editor_json_object())
        == mesh_editor_compact_json(right.type == JsonValue::Type::Object ? right : mesh_editor_json_object());
}

const std::vector<std::string>& mesh_editor_material_route_attr_names() {
    static const std::vector<std::string> names{
        "cdmw_material_authority_profile",
        "cdmw_material_authority_contract",
        "cdmw_source_material_name",
        "cdmw_target_material_name",
        "cdmw_target_material_slot_index",
        "cdmw_material_slot_kind",
        "cdmw_source_texture_set_key",
        "cdmw_material_route_status",
        "cdmw_material_route_reason",
        "preview_native_material_overrides",
    };
    return names;
}

void mesh_editor_clear_material_route_attrs(JsonValue& extra_attrs) {
    if (extra_attrs.type != JsonValue::Type::Object) {
        extra_attrs = mesh_editor_json_object();
    }
    for (const std::string& name : mesh_editor_material_route_attr_names()) {
        extra_attrs.object_value.erase(name);
    }
}

void mesh_editor_merge_extra_attrs(JsonValue& target, const JsonValue* patch) {
    if (patch == nullptr || patch->type != JsonValue::Type::Object) {
        return;
    }
    if (target.type != JsonValue::Type::Object) {
        target = mesh_editor_json_object();
    }
    for (const auto& entry : patch->object_value) {
        target.object_value[entry.first] = entry.second;
    }
}

bool mesh_editor_material_assign_has_payload(const JsonValue& edit) {
    if (edit.get("material") != nullptr || edit.get("texture") != nullptr) {
        return true;
    }
    const JsonValue* extra_attrs = edit.get("material_extra_attrs");
    return extra_attrs != nullptr && extra_attrs->type == JsonValue::Type::Object && !extra_attrs->object_value.empty();
}

void mesh_editor_apply_material_assign(MeshSessionSubmesh& submesh, const JsonValue& edit) {
    const bool identity_changed = edit.get("material") != nullptr || edit.get("texture") != nullptr;
    if (const JsonValue* material = edit.get("material")) {
        submesh.material = string_or(material, "");
    }
    if (const JsonValue* texture = edit.get("texture")) {
        submesh.texture = string_or(texture, "");
    }
    if (identity_changed) {
        mesh_editor_clear_material_route_attrs(submesh.extra_attrs);
    }
    mesh_editor_merge_extra_attrs(submesh.extra_attrs, edit.get("material_extra_attrs"));
}

void mesh_editor_apply_material_copy(MeshSessionSubmesh& target, const MeshSessionSubmesh& source, int source_index) {
    target.material = source.material;
    target.texture = source.texture;
    target.extra_attrs = mesh_editor_extra_attrs_object(source);
    if (target.extra_attrs.type != JsonValue::Type::Object) {
        target.extra_attrs = mesh_editor_json_object();
    }
    JsonValue source_index_value;
    source_index_value.type = JsonValue::Type::Number;
    source_index_value.number_value = source_index;
    target.extra_attrs.object_value["cdmw_mesh_edit_material_source_submesh_index"] = source_index_value;
}
