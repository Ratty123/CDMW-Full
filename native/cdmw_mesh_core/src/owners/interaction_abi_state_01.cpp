struct MeshInteractionProjectedVertex {
    int submesh_index = -1;
    int vertex_index = -1;
    double x = 0.0;
    double y = 0.0;
    double depth = 0.0;
};

struct MeshInteractionProjectedEdge {
    int submesh_index = -1;
    int vertex_a = -1;
    int vertex_b = -1;
    std::array<double, 4> bounds{};
};

struct MeshInteractionProjectedFace {
    int submesh_index = -1;
    int face_index = -1;
    std::array<int, 3> vertices{};
    std::array<double, 9> projected{};
    std::array<double, 4> bounds{};
};

struct MeshInteractionDepthBvhNode {
    std::array<double, 4> bounds{};
    int left = -1;
    int right = -1;
    std::size_t first = 0;
    std::size_t count = 0;
};

struct MeshInteractionSnapshot {
    bool ready = false;
    uint64_t mesh_revision = 0;
    uint64_t topology_generation = 0;
    uint64_t camera_revision = 0;
    uint64_t viewport_revision = 0;
    uint64_t visible_parts_revision = 0;
    uint64_t model_transform_revision = 0;
    bool xray = false;
    std::vector<MeshInteractionProjectedVertex> vertices;
    std::map<int, std::vector<std::size_t>> vertex_lookup;
    std::unordered_map<int64_t, std::vector<std::size_t>> vertex_buckets;
    std::vector<MeshInteractionProjectedEdge> edges;
    std::unordered_map<int64_t, std::vector<std::size_t>> edge_buckets;
    std::vector<std::size_t> large_edges;
    std::vector<MeshInteractionProjectedFace> faces;
    std::unordered_map<int64_t, std::vector<std::size_t>> face_buckets;
    std::vector<std::size_t> large_faces;
    std::map<int, std::vector<std::vector<int>>> adjacency;
    std::vector<std::size_t> depth_face_order;
    std::vector<MeshInteractionDepthBvhNode> depth_bvh;
};

struct MeshInteractionAbiSession {
    std::mutex mutex;
    bool closed = false;
    uint64_t handle = 0;
    uint64_t session_key = 0;
    std::string editor_session_id;
    uint64_t mesh_revision = 0;
    uint64_t selection_revision = 0;
    uint64_t topology_generation = 0;
    uint64_t camera_revision = 0;
    uint64_t viewport_revision = 0;
    uint64_t interaction_generation = 0;
    uint64_t active_gesture_id = 0;
    uint32_t active_tool = 0;
    uint32_t operator_state = CDMW_MESH_OPERATOR_IDLE;
    std::array<double, 16> world_view_projection{};
    std::map<int, std::array<double, 16>> submesh_world_view_projections;
    bool camera_valid = false;
    double viewport_width = 0.0;
    double viewport_height = 0.0;
    MeshEditorSelection baseline_selection;
    MeshEditorSelection gesture_selection_candidates;
    MeshEditorSelection last_selection;
    MeshInteractionSnapshot snapshot;
    std::map<int, std::map<int, Vec3>> gesture_before_positions;
    std::map<int, std::map<int, double>> gesture_weights;
    std::map<int, std::set<int>> gesture_changed_vertices;
    std::map<int, std::set<int>> last_dirty_vertices;
    double previous_screen_x = 0.0;
    double previous_screen_y = 0.0;
};

struct MeshInteractionAbiDirtySet {
    bool full = false;
    uint32_t vertex_count = 0;
    std::set<int> indices;
};

std::map<uint64_t, std::shared_ptr<MeshInteractionAbiSession>> g_mesh_interaction_abi_sessions;
std::map<uint64_t, uint64_t> g_mesh_interaction_abi_session_keys;
uint64_t g_mesh_interaction_abi_next_handle = 1;
std::shared_mutex g_mesh_interaction_abi_registry_mutex;
std::shared_mutex g_mesh_interaction_abi_editor_registry_mutex;

std::map<int, MeshSessionSubmesh>* mesh_interaction_abi_find_submeshes(
    const MeshInteractionAbiSession& session
);

JsonValue mesh_interaction_abi_json_number(double value) {
    JsonValue result;
    result.type = JsonValue::Type::Number;
    result.number_value = value;
    return result;
}

JsonValue mesh_interaction_abi_json_string(const std::string& value) {
    JsonValue result;
    result.type = JsonValue::Type::String;
    result.string_value = value;
    return result;
}

JsonValue mesh_interaction_abi_json_bool(bool value) {
    JsonValue result;
    result.type = JsonValue::Type::Bool;
    result.bool_value = value;
    return result;
}

JsonValue mesh_interaction_abi_json_object() {
    JsonValue result;
    result.type = JsonValue::Type::Object;
    return result;
}

JsonValue mesh_interaction_abi_json_array() {
    JsonValue result;
    result.type = JsonValue::Type::Array;
    return result;
}

JsonValue mesh_interaction_abi_vec3(double x, double y, double z) {
    JsonValue result = mesh_interaction_abi_json_array();
    result.array_value.push_back(mesh_interaction_abi_json_number(x));
    result.array_value.push_back(mesh_interaction_abi_json_number(y));
    result.array_value.push_back(mesh_interaction_abi_json_number(z));
    return result;
}

uint32_t mesh_interaction_abi_validate_header(
    const void* value,
    uint32_t actual_size,
    uint32_t expected_size,
    uint32_t version,
    std::string& message
) {
    if (value == nullptr) {
        message = "request is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    if (actual_size != expected_size) {
        message = "request struct_size does not match ABI v1";
        return CDMW_MESH_INTERACTION_INVALID_SIZE;
    }
    if (version != CDMW_MESH_INTERACTION_ABI_VERSION) {
        message = "request struct_version is not supported";
        return CDMW_MESH_INTERACTION_UNSUPPORTED_VERSION;
    }
    return CDMW_MESH_INTERACTION_OK;
}

uint32_t mesh_interaction_abi_validate_result(
    CdmwMeshInteractionResultV1* result,
    std::string& message
) {
    if (result == nullptr) {
        message = "result is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    const uint32_t status = mesh_interaction_abi_validate_header(
        result,
        result->struct_size,
        sizeof(CdmwMeshInteractionResultV1),
        result->struct_version,
        message
    );
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    if ((result->dirty_range_capacity > 0 && result->dirty_ranges == nullptr)
        || (result->selection_change_capacity > 0 && result->selection_changes == nullptr)) {
        message = "result buffer pointer is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    return CDMW_MESH_INTERACTION_OK;
}

void mesh_interaction_abi_write_message(
    CdmwMeshInteractionResultV1* result,
    const std::string& message
) {
    if (result == nullptr) return;
    std::memset(result->message, 0, sizeof(result->message));
    const std::size_t count = std::min(message.size(), sizeof(result->message) - 1);
    if (count > 0) std::memcpy(result->message, message.data(), count);
}

void mesh_interaction_abi_clear_result(CdmwMeshInteractionResultV1* result) {
    const uint32_t size = result->struct_size;
    const uint32_t version = result->struct_version;
    const uint32_t dirty_capacity = result->dirty_range_capacity;
    CdmwMeshDirtyRangeV1* dirty_ranges = result->dirty_ranges;
    const uint32_t selection_capacity = result->selection_change_capacity;
    CdmwMeshSelectionChangeV1* selection_changes = result->selection_changes;
    std::memset(result, 0, sizeof(*result));
    result->struct_size = size;
    result->struct_version = version;
    result->dirty_range_capacity = dirty_capacity;
    result->dirty_ranges = dirty_ranges;
    result->selection_change_capacity = selection_capacity;
    result->selection_changes = selection_changes;
}

uint32_t mesh_interaction_abi_fail(
    CdmwMeshInteractionResultV1* result,
    uint32_t status,
    const std::string& message
) {
    if (result != nullptr
        && result->struct_size == sizeof(CdmwMeshInteractionResultV1)
        && result->struct_version == CDMW_MESH_INTERACTION_ABI_VERSION) {
        result->status = status;
        mesh_interaction_abi_write_message(result, message);
    }
    return status;
}

void mesh_interaction_abi_append_dirty_sets(
    const std::map<int, MeshInteractionAbiDirtySet>& dirty,
    const MeshInteractionAbiSession& session,
    std::vector<CdmwMeshDirtyRangeV1>& ranges
) {
    for (const auto& item : dirty) {
        if (item.second.full) {
            ranges.push_back(CdmwMeshDirtyRangeV1{
                sizeof(CdmwMeshDirtyRangeV1), CDMW_MESH_INTERACTION_ABI_VERSION,
                item.first, 0, item.second.vertex_count,
                session.mesh_revision, session.topology_generation, session.interaction_generation
            });
            continue;
        }
        auto current = item.second.indices.begin();
        while (current != item.second.indices.end()) {
            const int start = *current;
            int finish = start + 1;
            ++current;
            while (current != item.second.indices.end() && *current == finish) {
                ++finish;
                ++current;
            }
            ranges.push_back(CdmwMeshDirtyRangeV1{
                sizeof(CdmwMeshDirtyRangeV1), CDMW_MESH_INTERACTION_ABI_VERSION,
                item.first, static_cast<uint32_t>(start), static_cast<uint32_t>(finish - start),
                session.mesh_revision, session.topology_generation, session.interaction_generation
            });
        }
    }
}

void mesh_interaction_abi_collect_full_dirty(
    const MeshInteractionAbiSession& runtime,
    std::map<int, MeshInteractionAbiDirtySet>& dirty
) {
    const auto* submeshes = mesh_interaction_abi_find_submeshes(runtime);
    if (submeshes == nullptr) return;
    for (const auto& item : *submeshes) {
        MeshInteractionAbiDirtySet& target = dirty[item.first];
        target.full = true;
        target.vertex_count = static_cast<uint32_t>(item.second.vertices.size());
        target.indices.clear();
    }
}

void mesh_interaction_abi_collect_history_dirty(
    const MeshInteractionAbiSession& runtime,
    const MeshEditorHistoryEntry& entry,
    std::map<int, MeshInteractionAbiDirtySet>& dirty
) {
    const auto* submeshes_pointer = mesh_interaction_abi_find_submeshes(runtime);
    if (submeshes_pointer == nullptr) return;
    const auto& submeshes = *submeshes_pointer;
    for (const auto& item : entry.deltas) {
        MeshInteractionAbiDirtySet& target = dirty[item.first];
        if (!item.second.vertices.before_replacement.empty()
            || !item.second.vertices.after_replacement.empty()) {
            const auto current = submeshes.find(item.first);
            target.full = true;
            target.vertex_count = current == submeshes.end()
                ? 0u : static_cast<uint32_t>(current->second.vertices.size());
            target.indices.clear();
        } else if (!target.full) {
            target.indices.insert(
                item.second.vertices.indices.begin(), item.second.vertices.indices.end()
            );
        }
    }
    for (const auto& item : entry.before) {
        const auto current = submeshes.find(item.first);
        MeshInteractionAbiDirtySet& target = dirty[item.first];
        target.full = true;
        target.vertex_count = current == submeshes.end()
            ? static_cast<uint32_t>(item.second.vertices.size())
            : static_cast<uint32_t>(current->second.vertices.size());
        target.indices.clear();
    }
}

void mesh_interaction_abi_collect_stroke_dirty(
    const MeshInteractionAbiSession& runtime,
    const MeshEditorSession& editor,
    uint64_t gesture_id,
    std::map<int, MeshInteractionAbiDirtySet>& dirty
) {
    const std::string stroke_id = std::to_string(gesture_id);
    for (auto item = editor.undo_stack.rbegin(); item != editor.undo_stack.rend(); ++item) {
        if (item->stroke_id != stroke_id) break;
        mesh_interaction_abi_collect_history_dirty(runtime, *item, dirty);
    }
}

template <typename T>
void mesh_interaction_abi_append_set_changes(
    int submesh_index,
    uint32_t target,
    const std::set<T>& before,
    const std::set<T>& after,
    const MeshInteractionAbiSession& session,
    std::vector<CdmwMeshSelectionChangeV1>& changes
) {
    std::set<T> values;
    std::set_symmetric_difference(
        before.begin(), before.end(), after.begin(), after.end(),
        std::inserter(values, values.end())
    );
    for (const T& value : values) {
        const bool selected = after.find(value) != after.end();
        changes.push_back(CdmwMeshSelectionChangeV1{
            sizeof(CdmwMeshSelectionChangeV1), CDMW_MESH_INTERACTION_ABI_VERSION,
            submesh_index, target, static_cast<uint32_t>(value), UINT32_MAX, 1,
            selected ? 1u : 0u, session.selection_revision, session.interaction_generation
        });
    }
}

void mesh_interaction_abi_append_edge_changes(
    int submesh_index,
    const std::set<std::array<int, 2>>& before,
    const std::set<std::array<int, 2>>& after,
    const MeshInteractionAbiSession& session,
    std::vector<CdmwMeshSelectionChangeV1>& changes
) {
    std::set<std::array<int, 2>> values;
    std::set_symmetric_difference(
        before.begin(), before.end(), after.begin(), after.end(),
        std::inserter(values, values.end())
    );
    for (const auto& value : values) {
        changes.push_back(CdmwMeshSelectionChangeV1{
            sizeof(CdmwMeshSelectionChangeV1), CDMW_MESH_INTERACTION_ABI_VERSION,
            submesh_index, CDMW_MESH_SELECTION_EDGE,
            static_cast<uint32_t>(value[0]), static_cast<uint32_t>(value[1]), 1,
            after.find(value) != after.end() ? 1u : 0u,
            session.selection_revision, session.interaction_generation
        });
    }
}

template <typename Mapping>
std::set<int> mesh_interaction_abi_mapping_keys(const Mapping& before, const Mapping& after) {
    std::set<int> keys;
    for (const auto& item : before) keys.insert(item.first);
    for (const auto& item : after) keys.insert(item.first);
    return keys;
}

void mesh_interaction_abi_append_selection_changes(
    const MeshEditorSelection& before,
    const MeshEditorSelection& after,
    const MeshInteractionAbiSession& session,
    std::vector<CdmwMeshSelectionChangeV1>& changes
) {
    static const std::set<int> empty_indices;
    static const std::set<std::array<int, 2>> empty_edges;
    for (const int index : mesh_interaction_abi_mapping_keys(before.vertices, after.vertices)) {
        const auto left = before.vertices.find(index);
        const auto right = after.vertices.find(index);
        mesh_interaction_abi_append_set_changes(
            index, CDMW_MESH_SELECTION_VERTEX,
            left == before.vertices.end() ? empty_indices : left->second,
            right == after.vertices.end() ? empty_indices : right->second,
            session, changes
        );
    }
    for (const int index : mesh_interaction_abi_mapping_keys(before.faces, after.faces)) {
        const auto left = before.faces.find(index);
        const auto right = after.faces.find(index);
        mesh_interaction_abi_append_set_changes(
            index, CDMW_MESH_SELECTION_FACE,
            left == before.faces.end() ? empty_indices : left->second,
            right == after.faces.end() ? empty_indices : right->second,
            session, changes
        );
    }
    for (const int index : mesh_interaction_abi_mapping_keys(before.edges, after.edges)) {
        const auto left = before.edges.find(index);
        const auto right = after.edges.find(index);
        mesh_interaction_abi_append_edge_changes(
            index,
            left == before.edges.end() ? empty_edges : left->second,
            right == after.edges.end() ? empty_edges : right->second,
            session, changes
        );
    }
}

uint32_t mesh_interaction_abi_finish_result(
    MeshInteractionAbiSession* session,
    CdmwMeshInteractionResultV1* result,
    const std::vector<CdmwMeshDirtyRangeV1>& dirty,
    const std::vector<CdmwMeshSelectionChangeV1>& selection_changes,
    const std::string& message = ""
) {
    if (session != nullptr) {
        result->session_handle = session->handle;
        result->gesture_id = session->active_gesture_id;
        result->operator_state = session->operator_state;
        result->mesh_revision = session->mesh_revision;
        result->selection_revision = session->selection_revision;
        result->topology_generation = session->topology_generation;
        result->camera_revision = session->camera_revision;
        result->viewport_revision = session->viewport_revision;
        result->interaction_generation = session->interaction_generation;
    }
    result->dirty_range_count = static_cast<uint32_t>(dirty.size());
    result->selection_change_count = static_cast<uint32_t>(selection_changes.size());
    const std::size_t dirty_copy = std::min<std::size_t>(dirty.size(), result->dirty_range_capacity);
    const std::size_t selection_copy = std::min<std::size_t>(
        selection_changes.size(), result->selection_change_capacity
    );
    for (std::size_t index = 0; index < dirty_copy; ++index) result->dirty_ranges[index] = dirty[index];
    for (std::size_t index = 0; index < selection_copy; ++index) {
        result->selection_changes[index] = selection_changes[index];
    }
    const bool short_buffer = dirty.size() > result->dirty_range_capacity
        || selection_changes.size() > result->selection_change_capacity;
    result->status = short_buffer ? CDMW_MESH_INTERACTION_BUFFER_TOO_SMALL : CDMW_MESH_INTERACTION_OK;
    mesh_interaction_abi_write_message(
        result,
        short_buffer ? "result buffers are smaller than the required descriptor counts" : message
    );
    return result->status;
}
