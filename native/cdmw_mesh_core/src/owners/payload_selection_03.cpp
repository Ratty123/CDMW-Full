std::vector<double> double_vector_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(double), "f64");
    std::vector<double> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / sizeof(double);
    result.resize(count);
    std::memcpy(result.data(), bytes.data(), bytes.size());
    for (const double item : result) {
        if (!std::isfinite(item)) {
            throw std::runtime_error("non-finite binary f64 payload");
        }
    }
    return result;
}

std::vector<double> double_vector_from_f32_or_f64_binary(const JsonValue* value) {
    const std::string kind = string_or(value != nullptr && value->type == JsonValue::Type::Object ? value->get("type") : nullptr, "f64");
    if (kind == "f32") {
        const std::vector<char> bytes = read_binary_payload(value, sizeof(float), "f32");
        std::vector<double> result;
        if (bytes.empty()) {
            return result;
        }
        const std::size_t count = bytes.size() / sizeof(float);
        std::vector<float> raw(count);
        std::memcpy(raw.data(), bytes.data(), bytes.size());
        result.reserve(count);
        for (const float item : raw) {
            if (!std::isfinite(item)) {
                throw std::runtime_error("non-finite binary f32 payload");
            }
            result.push_back(static_cast<double>(item));
        }
        return result;
    }
    return double_vector_from_binary(value);
}

std::vector<int> int_vector_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    const std::string& range_start_key,
    const std::string& range_count_key,
    const std::string& range_stride_key
) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return int_vector_from_binary(binary);
    }
    std::vector<int> range = int_vector_from_range_fields(item, range_start_key, range_count_key, range_stride_key);
    if (!range.empty()) {
        return range;
    }
    return int_vector_from_json(item.get(json_key));
}

std::vector<double> double_vector_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return double_vector_from_binary(binary);
    }
    return double_vector_from_json(item.get(json_key));
}

std::vector<Vec2> uvs_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(double) * 2, "vec2");
    std::vector<Vec2> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / (sizeof(double) * 2);
    std::vector<double> raw(count * 2);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        const Vec2 item{raw[index * 2], raw[index * 2 + 1]};
        if (!std::isfinite(item[0]) || !std::isfinite(item[1])) {
            throw std::runtime_error("non-finite binary vec2 payload");
        }
        result.push_back(item);
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_binary(const JsonValue* value, std::size_t vertex_count) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(std::int32_t) * 3, "faces");
    std::vector<std::array<int, 3>> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / (sizeof(std::int32_t) * 3);
    std::vector<std::int32_t> raw(count * 3);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        const int a = static_cast<int>(raw[index * 3]);
        const int b = static_cast<int>(raw[index * 3 + 1]);
        const int c = static_cast<int>(raw[index * 3 + 2]);
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            throw std::runtime_error("out-of-range binary face payload");
        }
        result.push_back({a, b, c});
    }
    return result;
}

std::vector<Vec3> vertices_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return vertices_from_binary(binary);
    }
    return vertices_from_json(item.get(json_key));
}

std::map<int, Vec3> indexed_vertices_from_binary_or_json(const JsonValue& item, int vertex_count) {
    const JsonValue* indices_binary = item.get("vertex_indices_binary");
    const JsonValue* positions_binary = item.get("vertex_positions_binary");
    const bool has_indices = indices_binary != nullptr
        || item.get("vertex_indices") != nullptr
        || item.get("vertex_index_start") != nullptr;
    if (has_indices && positions_binary != nullptr && vertex_count > 0) {
        const std::vector<int> indices = int_vector_from_binary_or_json(
            item,
            "vertex_indices_binary",
            "vertex_indices",
            "vertex_index_start",
            "vertex_index_count"
        );
        const std::vector<Vec3> positions = vertices_from_binary(positions_binary);
        std::map<int, Vec3> result;
        const std::size_t count = std::min(indices.size(), positions.size());
        for (std::size_t offset = 0; offset < count; ++offset) {
            const int index = indices[offset];
            if (index >= 0 && index < vertex_count) {
                result[index] = positions[offset];
            }
        }
        return result;
    }
    return indexed_vertices_from_json(item.get("vertex_positions"), vertex_count);
}

std::string sparse_snapshot_id_from_root(const JsonValue& root) {
    std::string snapshot_id = string_or(root.get("native_sparse_snapshot_id"), "");
    if (snapshot_id.empty()) {
        snapshot_id = string_or(root.get("sparse_snapshot_id"), "");
    }
    return snapshot_id;
}

void store_sparse_vertex_snapshot_values(
    const std::string& snapshot_id,
    int submesh_index,
    int vertex_count,
    const std::vector<int>& vertex_indices,
    const std::vector<Vec3>& positions
) {
    if (snapshot_id.empty() || submesh_index < 0 || vertex_count <= 0 || vertex_indices.size() != positions.size()) {
        return;
    }
    SparseVertexSnapshotSubmesh snapshot;
    snapshot.vertex_count = vertex_count;
    snapshot.vertex_indices = vertex_indices;
    snapshot.positions = positions;
    g_sparse_vertex_snapshots[snapshot_id][submesh_index] = std::move(snapshot);
}

std::map<int, Vec3> sparse_vertex_snapshot_positions_from_item(const JsonValue& item, int vertex_count) {
    std::string snapshot_id = string_or(item.get("native_sparse_snapshot_id"), "");
    if (snapshot_id.empty()) {
        snapshot_id = string_or(item.get("sparse_snapshot_id"), "");
    }
    if (snapshot_id.empty() || vertex_count <= 0) {
        return {};
    }
    const int submesh_index = int_or(item.get("index"), -1);
    if (submesh_index < 0) {
        return {};
    }
    const auto snapshot_found = g_sparse_vertex_snapshots.find(snapshot_id);
    if (snapshot_found == g_sparse_vertex_snapshots.end()) {
        return {};
    }
    const auto submesh_found = snapshot_found->second.find(submesh_index);
    if (submesh_found == snapshot_found->second.end()) {
        return {};
    }
    const SparseVertexSnapshotSubmesh& snapshot = submesh_found->second;
    if (snapshot.vertex_count != vertex_count || snapshot.vertex_indices.size() != snapshot.positions.size()) {
        return {};
    }
    const std::vector<int> requested = int_vector_from_binary_or_json(
        item,
        "vertex_indices_binary",
        "vertex_indices",
        "vertex_index_start",
        "vertex_index_count"
    );
    std::set<int> requested_set;
    for (const int index : requested) {
        if (index >= 0 && index < vertex_count) {
            requested_set.insert(index);
        }
    }
    std::map<int, Vec3> result;
    for (std::size_t offset = 0; offset < snapshot.vertex_indices.size(); ++offset) {
        const int index = snapshot.vertex_indices[offset];
        if (index < 0 || index >= vertex_count) {
            continue;
        }
        if (!requested_set.empty() && requested_set.find(index) == requested_set.end()) {
            continue;
        }
        result[index] = snapshot.positions[offset];
    }
    return result;
}

std::vector<Vec2> uvs_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key = "uvs_binary",
    const std::string& json_key = "uvs"
) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return uvs_from_binary(binary);
    }
    return uvs_from_json(item.get(json_key));
}

std::vector<std::array<int, 3>> faces_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    return faces_from_binary_or_json_keys(item, "faces_binary", "faces", vertex_count);
}

std::vector<std::array<int, 3>> faces_from_binary_or_json_keys(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t vertex_count
) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return faces_from_binary(binary, vertex_count);
    }
    return faces_from_json(item.get(json_key), vertex_count);
}

std::set<int> selected_vertices_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::set<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number) {
            continue;
        }
        int index = -1;
        if (!strict_int_or(&item, index)) {
            continue;
        }
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.insert(index);
        }
    }
    return result;
}

std::string normalized_selection_operation(std::string operation) {
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (operation == "extend") {
        operation = "add";
    } else if (operation == "remove") {
        operation = "subtract";
    }
    if (operation != "add" && operation != "subtract" && operation != "toggle") {
        operation = "replace";
    }
    return operation;
}

template <typename Value>
std::set<Value> combine_selection_sets(std::set<Value> current, const std::set<Value>& incoming, const std::string& operation) {
    if (operation == "add") {
        current.insert(incoming.begin(), incoming.end());
        return current;
    }
    if (operation == "subtract") {
        for (const Value& value : incoming) {
            current.erase(value);
        }
        return current;
    }
    if (operation == "toggle") {
        for (const Value& value : incoming) {
            const auto found = current.find(value);
            if (found == current.end()) {
                current.insert(value);
            } else {
                current.erase(found);
            }
        }
        return current;
    }
    return incoming;
}

const MeshEditorSession* mesh_editor_session_for_item(const JsonValue& item) {
    std::string session_id = string_or(item.get("editor_session_id"), "");
    if (session_id.empty()) {
        session_id = string_or(item.get("mesh_editor_session_id"), "");
    }
    if (session_id.empty() || int_or(item.get("index"), -1) < 0) {
        return nullptr;
    }
    const auto found = g_mesh_editor_sessions.find(session_id);
    return found == g_mesh_editor_sessions.end() ? nullptr : &found->second;
}

const MeshEditorSelection* mesh_editor_selection_for_item(const JsonValue& item) {
    const MeshEditorSession* session = mesh_editor_session_for_item(item);
    return session == nullptr ? nullptr : &session->selection;
}

std::set<int> mesh_editor_selected_indices_for_item(
    const JsonValue& item,
    const std::map<int, std::set<int>>& values_by_submesh,
    std::size_t item_count
) {
    std::set<int> result;
    const int submesh_index = int_or(item.get("index"), -1);
    const auto found = values_by_submesh.find(submesh_index);
    if (found == values_by_submesh.end()) {
        return result;
    }
    for (const int index : found->second) {
        if (index >= 0 && static_cast<std::size_t>(index) < item_count) {
            result.insert(index);
        }
    }
    return result;
}

std::set<std::array<int, 2>> mesh_editor_selected_edges_for_item(const JsonValue& item, std::size_t vertex_count) {
    std::set<std::array<int, 2>> result;
    const MeshEditorSelection* selection = mesh_editor_selection_for_item(item);
    if (selection == nullptr) {
        return result;
    }
    const int submesh_index = int_or(item.get("index"), -1);
    const auto found = selection->edges.find(submesh_index);
    if (found == selection->edges.end()) {
        return result;
    }
    for (const std::array<int, 2>& edge : found->second) {
        if (edge[0] >= 0 && edge[1] >= 0
            && static_cast<std::size_t>(edge[0]) < vertex_count
            && static_cast<std::size_t>(edge[1]) < vertex_count) {
            result.insert(edge);
        }
    }
    return result;
}

std::set<int> selected_vertices_from_binary_or_json_keys(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::string& binary_key,
    const std::string& json_key,
    const std::string& range_start_key = std::string(),
    const std::string& range_count_key = std::string()
) {
    std::set<int> result;
    const std::vector<int> values = int_vector_from_binary_or_json(
        item,
        binary_key,
        json_key,
        range_start_key,
        range_count_key
    );
    for (const int index : values) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.insert(index);
        }
    }
    return result;
}

std::set<int> selected_vertices_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    std::set<int> result;
    if (bool_or(item.get("selected_all_vertices"), false)) {
        for (std::size_t index = 0; index < vertex_count; ++index) {
            result.insert(static_cast<int>(index));
        }
        return result;
    }
    result = selected_vertices_from_binary_or_json_keys(
        item,
        vertex_count,
        "selected_vertices_binary",
        "selected_vertices",
        "selected_vertex_start",
        "selected_vertex_count"
    );
    if (!result.empty()) {
        return result;
    }
    if (const MeshEditorSelection* selection = mesh_editor_selection_for_item(item)) {
        return mesh_editor_selected_indices_for_item(item, selection->vertices, vertex_count);
    }
    return result;
}

std::map<int, double> selected_vertex_weights_from_editor_session(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::set<int>* allowed,
    bool& has_weights
) {
    has_weights = false;
    std::map<int, double> weights;
    const MeshEditorSelection* selection = mesh_editor_selection_for_item(item);
    if (selection == nullptr) {
        return weights;
    }
    const int submesh_index = int_or(item.get("index"), -1);
    const auto found = selection->vertex_weights.find(submesh_index);
    if (found == selection->vertex_weights.end()) {
        const std::set<int> selected = mesh_editor_selected_indices_for_item(item, selection->vertices, vertex_count);
        for (const int index : selected) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
                continue;
            }
            if (allowed != nullptr && allowed->find(index) == allowed->end()) {
                continue;
            }
            weights[index] = 1.0;
        }
        has_weights = !weights.empty();
        return weights;
    }
    has_weights = true;
    for (const auto& entry : found->second) {
        const int index = entry.first;
        if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
            continue;
        }
        if (allowed != nullptr && allowed->find(index) == allowed->end()) {
            continue;
        }
        const double weight = std::max(0.0, std::min(1.0, entry.second));
        if (weight > 0.0) {
            weights[index] = std::max(weights[index], weight);
        }
    }
    return weights;
}

std::set<int> selected_indices_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t item_count,
    const std::string& range_start_key = std::string(),
    const std::string& range_count_key = std::string()
) {
    std::set<int> result;
    const std::vector<int> values = int_vector_from_binary_or_json(
        item,
        binary_key,
        json_key,
        range_start_key,
        range_count_key
    );
    for (const int index : values) {
        if (index >= 0 && static_cast<std::size_t>(index) < item_count) {
            result.insert(index);
        }
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<std::array<int, 3>> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            continue;
        }
        int a = -1;
        int b = -1;
        int c = -1;
        if (!strict_int_or(&item.array_value[0], a)
            || !strict_int_or(&item.array_value[1], b)
            || !strict_int_or(&item.array_value[2], c)) {
            continue;
        }
        if (a >= 0 && b >= 0 && c >= 0
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count
            && static_cast<std::size_t>(c) < vertex_count) {
            result.push_back({a, b, c});
        }
    }
    return result;
}

std::vector<int> source_face_indices_from_faces_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (std::size_t face_index = 0; face_index < value->array_value.size(); ++face_index) {
        const JsonValue& item = value->array_value[face_index];
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            continue;
        }
        int a = -1;
        int b = -1;
        int c = -1;
        if (!strict_int_or(&item.array_value[0], a)
            || !strict_int_or(&item.array_value[1], b)
            || !strict_int_or(&item.array_value[2], c)) {
            continue;
        }
        if (a >= 0 && b >= 0 && c >= 0
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count
            && static_cast<std::size_t>(c) < vertex_count) {
            result.push_back(static_cast<int>(face_index));
        }
    }
    return result;
}

struct DisplayFace {
    std::vector<int> indices;
    int source_index = -1;
    bool valid = false;
};

std::vector<DisplayFace> display_faces_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<DisplayFace> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (std::size_t face_index = 0; face_index < value->array_value.size(); ++face_index) {
        const JsonValue& item = value->array_value[face_index];
        DisplayFace face;
        face.source_index = static_cast<int>(face_index);
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            result.push_back(std::move(face));
            continue;
        }
        bool valid = true;
        face.indices.reserve(item.array_value.size());
        for (const JsonValue& raw_index : item.array_value) {
            int vertex_index = -1;
            if (!strict_int_or(&raw_index, vertex_index)
                || vertex_index < 0
                || static_cast<std::size_t>(vertex_index) >= vertex_count) {
                valid = false;
                break;
            }
            face.indices.push_back(vertex_index);
        }
        face.valid = valid && face.indices.size() >= 3;
        if (!face.valid) {
            face.indices.clear();
        }
        result.push_back(std::move(face));
    }
    return result;
}

std::array<int, 2> edge_key(int a, int b) {
    return {std::min(a, b), std::max(a, b)};
}

std::vector<int> closed_edge_loop_order(const std::set<std::array<int, 2>>& edges) {
    std::vector<int> order;
    if (edges.size() != 3 && edges.size() != 4) {
        return order;
    }
    std::map<int, std::set<int>> adjacency;
    for (const auto& edge : edges) {
        if (edge[0] == edge[1]) {
            return {};
        }
        adjacency[edge[0]].insert(edge[1]);
        adjacency[edge[1]].insert(edge[0]);
    }
    if (adjacency.size() != edges.size()) {
        return {};
    }
    for (const auto& item_adjacency : adjacency) {
        if (item_adjacency.second.size() != 2) {
            return {};
        }
    }
    const int start = adjacency.begin()->first;
    int previous = start;
    int current = *adjacency[start].begin();
    order.push_back(start);
    while (current != start) {
        if (std::find(order.begin(), order.end(), current) != order.end()) {
            return {};
        }
        order.push_back(current);
        const std::set<int>& neighbors = adjacency[current];
        int next = -1;
        for (const int candidate : neighbors) {
            if (candidate != previous) {
                next = candidate;
                break;
            }
        }
        if (next < 0) {
            return {};
        }
        previous = current;
        current = next;
    }
    if (order.size() != adjacency.size()) {
        return {};
    }
    return order;
}

std::set<std::array<int, 2>> selected_edges_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::set<std::array<int, 2>> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        int a = -1;
        int b = -1;
        if (!strict_int_or(&item.array_value[0], a) || !strict_int_or(&item.array_value[1], b)) {
            continue;
        }
        if (a >= 0 && b >= 0 && a != b
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count) {
            result.insert(edge_key(a, b));
        }
    }
    return result;
}

std::set<std::array<int, 2>> selected_edges_from_binary_or_json_keys(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::string& binary_key,
    const std::string& json_key
) {
    std::set<std::array<int, 2>> result;
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        const std::vector<int> raw = int_vector_from_binary(binary);
        for (std::size_t offset = 0; offset + 1 < raw.size(); offset += 2) {
            const int a = raw[offset];
            const int b = raw[offset + 1];
            if (a >= 0 && b >= 0 && a != b
                && static_cast<std::size_t>(a) < vertex_count
                && static_cast<std::size_t>(b) < vertex_count) {
                result.insert(edge_key(a, b));
            }
        }
        return result;
    }
    result = selected_edges_from_json(item.get(json_key), vertex_count);
    if (!result.empty()) {
        return result;
    }
    return mesh_editor_selected_edges_for_item(item, vertex_count);
}

std::set<std::array<int, 2>> selected_edges_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    return selected_edges_from_binary_or_json_keys(item, vertex_count, "selected_edges_binary", "selected_edges");
}

bool source_face_indices_are_identity(const std::vector<int>& source_faces) {
    for (std::size_t index = 0; index < source_faces.size(); ++index) {
        if (source_faces[index] != static_cast<int>(index)) {
            return false;
        }
    }
    return true;
}

std::set<int> compact_face_offsets_from_selection_values(
    const std::set<int>& selected_values,
    const std::vector<int>& source_faces,
    std::size_t face_count
) {
    std::set<int> result;
    if (selected_values.empty()) {
        return result;
    }
    if (source_faces.size() == face_count && !source_face_indices_are_identity(source_faces)) {
        for (std::size_t face_offset = 0; face_offset < source_faces.size(); ++face_offset) {
            if (selected_values.find(source_faces[face_offset]) != selected_values.end()) {
                result.insert(static_cast<int>(face_offset));
            }
        }
        return result;
    }
    for (const int index : selected_values) {
        if (index >= 0 && static_cast<std::size_t>(index) < face_count) {
            result.insert(index);
        }
    }
    return result;
}

std::vector<int> source_face_indices_for_selection(
    const JsonValue& item,
    const std::vector<std::array<int, 3>>& faces,
    std::size_t vertex_count
) {
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() == faces.size() && !source_face_indices_are_identity(source_faces)) {
        return source_faces;
    }
    if (item.get("source_face_indices_binary") == nullptr
        && item.get("source_face_indices") == nullptr
        && item.get("source_face_start") == nullptr
        && item.get("faces") != nullptr) {
        const std::vector<int> raw_source_faces = source_face_indices_from_faces_json(item.get("faces"), vertex_count);
        if (raw_source_faces.size() == faces.size()) {
            return raw_source_faces;
        }
    }
    return source_faces;
}
