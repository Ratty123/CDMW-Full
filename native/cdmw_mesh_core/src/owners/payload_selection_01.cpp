void write_text_file(const std::string& path, const std::string& text) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    output << text;
}

void write_escaped(std::ostream& out, const std::string& text);
void write_json_value(std::ostream& out, const JsonValue& value);

void write_binary_file(const std::string& path, const std::vector<char>& data, bool append) {
    std::ofstream output(path, std::ios::binary | (append ? std::ios::app : std::ios::trunc));
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!data.empty()) {
        output.write(data.data(), static_cast<std::streamsize>(data.size()));
    }
}

void write_vec3_binary_file(const std::string& path, const std::vector<Vec3>& values) {
    static_assert(sizeof(Vec3) == sizeof(double) * 3, "Vec3 binary layout changed");
    if (path.empty()) {
        throw std::runtime_error("missing vec3 output path");
    }
    for (const Vec3& value : values) {
        if (!std::isfinite(value[0]) || !std::isfinite(value[1]) || !std::isfinite(value[2])) {
            throw std::runtime_error("non-finite vec3 output value: " + path);
        }
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!values.empty()) {
        output.write(
            reinterpret_cast<const char*>(values.data()),
            static_cast<std::streamsize>(values.size() * sizeof(Vec3))
        );
    }
    if (!output) {
        throw std::runtime_error("cannot write vec3 output file: " + path);
    }
}

void write_vec2_binary_file(const std::string& path, const std::vector<Vec2>& values) {
    static_assert(sizeof(Vec2) == sizeof(double) * 2, "Vec2 binary layout changed");
    if (path.empty()) {
        throw std::runtime_error("missing vec2 output path");
    }
    for (const Vec2& value : values) {
        if (!std::isfinite(value[0]) || !std::isfinite(value[1])) {
            throw std::runtime_error("non-finite vec2 output value: " + path);
        }
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!values.empty()) {
        output.write(
            reinterpret_cast<const char*>(values.data()),
            static_cast<std::streamsize>(values.size() * sizeof(Vec2))
        );
    }
    if (!output) {
        throw std::runtime_error("cannot write vec2 output file: " + path);
    }
}

void write_double_binary_file(const std::string& path, const std::vector<double>& values) {
    if (path.empty()) {
        throw std::runtime_error("missing f64 output path");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!values.empty()) {
        output.write(
            reinterpret_cast<const char*>(values.data()),
            static_cast<std::streamsize>(values.size() * sizeof(double))
        );
    }
    if (!output) {
        throw std::runtime_error("cannot write f64 output file: " + path);
    }
}

void write_int_binary_file(const std::string& path, const std::vector<int>& values) {
    if (path.empty()) {
        throw std::runtime_error("missing int output path");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (sizeof(int) == sizeof(std::int32_t)) {
        if (!values.empty()) {
            output.write(
                reinterpret_cast<const char*>(values.data()),
                static_cast<std::streamsize>(values.size() * sizeof(std::int32_t))
            );
        }
        if (!output) {
            throw std::runtime_error("cannot write int output file: " + path);
        }
        return;
    }
    for (const int value : values) {
        const std::int32_t raw = static_cast<std::int32_t>(value);
        output.write(reinterpret_cast<const char*>(&raw), static_cast<std::streamsize>(sizeof(raw)));
        if (!output) {
            throw std::runtime_error("cannot write int output file: " + path);
        }
    }
}

void write_faces_binary_file(const std::string& path, const std::vector<std::array<int, 3>>& faces) {
    if (path.empty()) {
        throw std::runtime_error("missing face output path");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (sizeof(std::array<int, 3>) == sizeof(std::int32_t) * 3) {
        if (!faces.empty()) {
            output.write(
                reinterpret_cast<const char*>(faces.data()),
                static_cast<std::streamsize>(faces.size() * sizeof(std::array<int, 3>))
            );
        }
        if (!output) {
            throw std::runtime_error("cannot write face output file: " + path);
        }
        return;
    }
    for (const auto& face : faces) {
        const std::int32_t raw[3] = {
            static_cast<std::int32_t>(face[0]),
            static_cast<std::int32_t>(face[1]),
            static_cast<std::int32_t>(face[2]),
        };
        output.write(reinterpret_cast<const char*>(raw), static_cast<std::streamsize>(sizeof(raw)));
        if (!output) {
            throw std::runtime_error("cannot write face output file: " + path);
        }
    }
}

double number_or(const JsonValue* value, double fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Number || !std::isfinite(value->number_value)) {
        return fallback;
    }
    return value->number_value;
}

int int_or(const JsonValue* value, int fallback) {
    const double number = number_or(value, static_cast<double>(fallback));
    if (number < static_cast<double>(INT_MIN) || number > static_cast<double>(INT_MAX)) {
        return fallback;
    }
    return static_cast<int>(number);
}

bool strict_int_or(const JsonValue* value, int& out) {
    if (value == nullptr || value->type != JsonValue::Type::Number || !std::isfinite(value->number_value)) {
        return false;
    }
    if (std::floor(value->number_value) != value->number_value
        || value->number_value < static_cast<double>(INT_MIN)
        || value->number_value > static_cast<double>(INT_MAX)) {
        return false;
    }
    out = static_cast<int>(value->number_value);
    return true;
}

bool bool_or(const JsonValue* value, bool fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Bool) {
        return fallback;
    }
    return value->bool_value;
}

std::string string_or(const JsonValue* value, const std::string& fallback = std::string()) {
    if (value == nullptr || value->type != JsonValue::Type::String) {
        return fallback;
    }
    return value->string_value;
}

std::string lower_ascii(std::string value);

void uv_align_from_json(
    const JsonValue* value,
    bool& has_value,
    bool& is_number,
    double& number,
    std::string& mode
) {
    has_value = false;
    is_number = false;
    number = 0.0;
    mode.clear();
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Number && std::isfinite(value->number_value)) {
        has_value = true;
        is_number = true;
        number = value->number_value;
        return;
    }
    if (value->type == JsonValue::Type::String) {
        has_value = true;
        mode = lower_ascii(value->string_value);
    }
}

std::vector<Vec3> vertices_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key);
std::vector<Vec2> uvs_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key);
std::vector<std::array<int, 3>> faces_from_binary_or_json_keys(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t vertex_count
);
std::vector<std::array<int, 3>> faces_from_binary_or_json(const JsonValue& item, std::size_t vertex_count);
std::vector<int> int_vector_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    const std::string& range_start_key = std::string(),
    const std::string& range_count_key = std::string(),
    const std::string& range_stride_key = std::string()
);
std::vector<double> double_vector_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key);
std::vector<Vec3> compute_smooth_normals(const std::vector<Vec3>& vertices, const std::vector<std::array<int, 3>>& faces);
bool valid_bone_assignments(const BoneAssignments& bones);

const MeshSessionSubmesh* mesh_session_submesh_for_item(const JsonValue& item) {
    const std::string session_id = string_or(item.get("session_id"), "");
    const int submesh_index = int_or(item.get("index"), -1);
    if (session_id.empty() || submesh_index < 0) {
        return nullptr;
    }
    const auto session_found = g_mesh_sessions.find(session_id);
    if (session_found == g_mesh_sessions.end()) {
        return nullptr;
    }
    const auto submesh_found = session_found->second.find(submesh_index);
    return submesh_found == session_found->second.end() ? nullptr : &submesh_found->second;
}

MeshSessionSubmesh* mutable_mesh_session_submesh_for_item(const JsonValue& item) {
    const std::string session_id = string_or(item.get("session_id"), "");
    const int submesh_index = int_or(item.get("index"), -1);
    if (session_id.empty() || submesh_index < 0) {
        return nullptr;
    }
    auto session_found = g_mesh_sessions.find(session_id);
    if (session_found == g_mesh_sessions.end()) {
        return nullptr;
    }
    auto submesh_found = session_found->second.find(submesh_index);
    return submesh_found == session_found->second.end() ? nullptr : &submesh_found->second;
}

const MeshSessionSubmesh* mesh_snapshot_submesh_for_item(const std::string& snapshot_id, const JsonValue& item) {
    const int submesh_index = int_or(item.get("index"), -1);
    if (snapshot_id.empty() || submesh_index < 0) {
        return nullptr;
    }
    const auto snapshot_found = g_mesh_snapshots.find(snapshot_id);
    if (snapshot_found == g_mesh_snapshots.end()) {
        return nullptr;
    }
    const auto submesh_found = snapshot_found->second.find(submesh_index);
    return submesh_found == snapshot_found->second.end() ? nullptr : &submesh_found->second;
}

bool item_has_direct_geometry(const JsonValue& item, const std::string& binary_key, const std::string& json_key) {
    return item.get(binary_key) != nullptr || item.get(json_key) != nullptr;
}

std::vector<Vec3> mesh_vertices_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "vertices_binary", "vertices")) {
        return vertices_from_binary_or_json(item, "vertices_binary", "vertices");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->vertices;
    }
    if (!string_or(item.get("session_id"), "").empty()) {
        throw std::runtime_error("missing native mesh session vertices");
    }
    return {};
}

std::size_t mesh_vertex_count_from_item(const JsonValue& item) {
    const int explicit_count = int_or(item.get("vertex_count"), -1);
    if (explicit_count >= 0) {
        return static_cast<std::size_t>(explicit_count);
    }
    if (item_has_direct_geometry(item, "vertices_binary", "vertices")) {
        return vertices_from_binary_or_json(item, "vertices_binary", "vertices").size();
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->vertices.size();
    }
    if (!string_or(item.get("session_id"), "").empty()) {
        throw std::runtime_error("missing native mesh session vertex count");
    }
    return 0;
}

std::vector<std::array<int, 3>> mesh_faces_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("faces_binary") != nullptr || item.get("faces") != nullptr) {
        return faces_from_binary_or_json(item, vertex_count);
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->vertices.size() == vertex_count) {
            return session->faces;
        }
        return {};
    }
    if (!string_or(item.get("session_id"), "").empty()) {
        throw std::runtime_error("missing native mesh session faces");
    }
    return {};
}

std::vector<int> identity_indices(std::size_t count) {
    std::vector<int> result;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        result.push_back(static_cast<int>(index));
    }
    return result;
}

bool contiguous_int_range(const std::vector<int>& values, int& start) {
    if (values.empty()) {
        return false;
    }
    start = values.front();
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (values[index] != start + static_cast<int>(index)) {
            return false;
        }
    }
    return true;
}

bool contiguous_int_stride_range(const std::vector<int>& values, int& start, int& stride) {
    if (values.empty()) {
        return false;
    }
    start = values.front();
    if (values.size() == 1) {
        stride = 1;
        return true;
    }
    stride = values[1] - values[0];
    if (stride <= 0) {
        return false;
    }
    for (std::size_t index = 0; index < values.size(); ++index) {
        const long long expected = static_cast<long long>(start)
            + static_cast<long long>(index) * static_cast<long long>(stride);
        if (expected < static_cast<long long>(INT_MIN)
            || expected > static_cast<long long>(INT_MAX)
            || values[index] != static_cast<int>(expected)) {
            return false;
        }
    }
    return true;
}

std::vector<int> int_vector_from_range_fields(
    const JsonValue& item,
    const std::string& range_start_key,
    const std::string& range_count_key,
    const std::string& range_stride_key = std::string()
) {
    std::vector<int> result;
    if (range_start_key.empty() || range_count_key.empty()) {
        return result;
    }
    const int start = int_or(item.get(range_start_key), -1);
    const int count = int_or(item.get(range_count_key), 0);
    const int stride = range_stride_key.empty() ? 1 : int_or(item.get(range_stride_key), 1);
    if (start < 0 || count <= 0) {
        return result;
    }
    if (stride == 0) {
        return result;
    }
    result.reserve(static_cast<std::size_t>(count));
    for (int offset = 0; offset < count; ++offset) {
        const long long value = static_cast<long long>(start) + static_cast<long long>(offset) * static_cast<long long>(stride);
        if (value < static_cast<long long>(INT_MIN) || value > static_cast<long long>(INT_MAX)) {
            return {};
        }
        result.push_back(static_cast<int>(value));
    }
    return result;
}

std::vector<int> mesh_source_vertex_indices_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("source_vertex_indices_binary") != nullptr
        || item.get("source_vertex_indices") != nullptr
        || item.get("source_vertex_start") != nullptr) {
        std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_vertex_indices_binary",
            "source_vertex_indices",
            "source_vertex_start",
            "source_vertex_count"
        );
        if (values.size() > vertex_count) {
            values.resize(vertex_count);
        }
        return values;
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_vertex_map.size() == vertex_count) {
            return session->source_vertex_map;
        }
    }
    return identity_indices(vertex_count);
}

std::vector<int> mesh_source_face_indices_from_item(const JsonValue& item, std::size_t face_count) {
    if (item.get("source_face_indices_binary") != nullptr
        || item.get("source_face_indices") != nullptr
        || item.get("source_face_start") != nullptr) {
        std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_face_indices_binary",
            "source_face_indices",
            "source_face_start",
            "source_face_count"
        );
        if (values.size() > face_count) {
            values.resize(face_count);
        }
        return values;
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_face_indices.size() == face_count) {
            return session->source_face_indices;
        }
    }
    return identity_indices(face_count);
}

std::vector<int> mesh_source_vertex_map_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("source_vertex_map_binary") != nullptr
        || item.get("source_vertex_map") != nullptr
        || item.get("source_vertex_map_start") != nullptr) {
        const std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_vertex_map_binary",
            "source_vertex_map",
            "source_vertex_map_start",
            "source_vertex_map_count"
        );
        if (values.size() == vertex_count) {
            return values;
        }
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_vertex_map.size() == vertex_count) {
            return session->source_vertex_map;
        }
    }
    return identity_indices(vertex_count);
}

std::vector<int> source_vertex_offsets_from_item(const JsonValue& item) {
    return int_vector_from_binary_or_json(
        item,
        "source_vertex_offsets_binary",
        "source_vertex_offsets",
        "source_vertex_offsets_start",
        "source_vertex_offsets_count",
        "source_vertex_offsets_stride"
    );
}

std::string filename_from_path(const std::string& path) {
    const std::size_t pos = path.find_last_of("/\\");
    if (pos == std::string::npos) {
        return path;
    }
    return path.substr(pos + 1);
}

std::string utc_timestamp_seconds() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t raw_time = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &raw_time);
#else
    gmtime_r(&raw_time, &utc);
#endif
    char buffer[32] = {};
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return std::string(buffer);
}

std::vector<Vec3> mesh_normals_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "normals_binary", "normals")) {
        return vertices_from_binary_or_json(item, "normals_binary", "normals");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->normals;
    }
    return {};
}

std::vector<Vec2> mesh_uvs_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "uvs_binary", "uvs")) {
        return uvs_from_binary_or_json(item, "uvs_binary", "uvs");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->uvs;
    }
    return {};
}

std::vector<Vec3> mesh_tangents_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "tangents_binary", "tangents")) {
        return vertices_from_binary_or_json(item, "tangents_binary", "tangents");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->tangents;
    }
    return {};
}

std::vector<double> mesh_tangent_signs_from_item(const JsonValue& item) {
    if (item.get("tangent_signs_binary") != nullptr || item.get("tangent_signs") != nullptr) {
        return double_vector_from_binary_or_json(item, "tangent_signs_binary", "tangent_signs");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->tangent_signs;
    }
    return {};
}

BoneAssignments bone_assignments_from_binary(const JsonValue& item) {
    BoneAssignments result;
    if (item.get("bone_counts_binary") == nullptr || item.get("bone_indices_binary") == nullptr || item.get("bone_weights_binary") == nullptr) {
        return result;
    }
    const std::vector<int> counts = int_vector_from_binary_or_json(item, "bone_counts_binary", "bone_counts");
    const std::vector<int> flat_indices = int_vector_from_binary_or_json(item, "bone_indices_binary", "bone_indices_flat");
    const std::vector<double> flat_weights = double_vector_from_binary_or_json(item, "bone_weights_binary", "bone_weights_flat");
    if (flat_indices.size() != flat_weights.size()) {
        return {};
    }
    std::size_t flat_offset = 0;
    result.indices.reserve(counts.size());
    result.weights.reserve(counts.size());
    for (const int raw_count : counts) {
        if (raw_count < 0) {
            return {};
        }
        const std::size_t count = static_cast<std::size_t>(raw_count);
        if (flat_offset + count > flat_indices.size()) {
            return {};
        }
        std::vector<int> indices;
        std::vector<double> weights;
        indices.reserve(count);
        weights.reserve(count);
        for (std::size_t index = 0; index < count; ++index) {
            const int bone = flat_indices[flat_offset + index];
            const double weight = flat_weights[flat_offset + index];
            if (bone < 0 || !std::isfinite(weight)) {
                return {};
            }
            indices.push_back(bone);
            weights.push_back(weight);
        }
        result.indices.push_back(std::move(indices));
        result.weights.push_back(std::move(weights));
        flat_offset += count;
    }
    if (flat_offset != flat_indices.size()) {
        return {};
    }
    return result;
}

BoneAssignments mesh_bones_from_item(const JsonValue& item) {
    BoneAssignments direct = bone_assignments_from_binary(item);
    if (!direct.indices.empty() || item.get("bone_counts_binary") != nullptr) {
        return direct;
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return {session->bone_indices, session->bone_weights};
    }
    return {};
}

std::vector<int> int_vector_from_json(const JsonValue* value) {
    std::vector<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value)) {
            continue;
        }
        if (item.number_value < static_cast<double>(INT_MIN) || item.number_value > static_cast<double>(INT_MAX)) {
            continue;
        }
        result.push_back(static_cast<int>(item.number_value));
    }
    return result;
}

std::vector<double> double_vector_from_json(const JsonValue* value) {
    std::vector<double> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value)) {
            result.push_back(1.0);
            continue;
        }
        result.push_back(item.number_value);
    }
    return result;
}

bool matrix4x4_from_json(const JsonValue* value, std::array<double, 16>& matrix) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() != matrix.size()) {
        return false;
    }
    for (std::size_t index = 0; index < matrix.size(); ++index) {
        const JsonValue& item = value->array_value[index];
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value)) {
            return false;
        }
        matrix[index] = item.number_value;
    }
    return true;
}

bool matrix4x4_inverse(const std::array<double, 16>& matrix, std::array<double, 16>& inverse) {
    std::array<std::array<double, 8>, 4> work{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            work[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)] =
                matrix[static_cast<std::size_t>(row * 4 + column)];
        }
        work[static_cast<std::size_t>(row)][static_cast<std::size_t>(4 + row)] = 1.0;
    }
    for (int column = 0; column < 4; ++column) {
        int pivot = column;
        double pivot_abs = std::abs(work[static_cast<std::size_t>(pivot)][static_cast<std::size_t>(column)]);
        for (int row = column + 1; row < 4; ++row) {
            const double candidate = std::abs(work[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)]);
            if (candidate > pivot_abs) {
                pivot = row;
                pivot_abs = candidate;
            }
        }
        if (!std::isfinite(pivot_abs) || pivot_abs <= 1e-12) {
            return false;
        }
        if (pivot != column) {
            std::swap(work[static_cast<std::size_t>(pivot)], work[static_cast<std::size_t>(column)]);
        }
        const double divisor = work[static_cast<std::size_t>(column)][static_cast<std::size_t>(column)];
        for (double& value : work[static_cast<std::size_t>(column)]) {
            value /= divisor;
        }
        for (int row = 0; row < 4; ++row) {
            if (row == column) {
                continue;
            }
            const double factor = work[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)];
            if (std::abs(factor) <= 1e-18) {
                continue;
            }
            for (int item = 0; item < 8; ++item) {
                work[static_cast<std::size_t>(row)][static_cast<std::size_t>(item)] -=
                    factor * work[static_cast<std::size_t>(column)][static_cast<std::size_t>(item)];
            }
        }
    }
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            const double value = work[static_cast<std::size_t>(row)][static_cast<std::size_t>(4 + column)];
            if (!std::isfinite(value)) {
                return false;
            }
            inverse[static_cast<std::size_t>(row * 4 + column)] = value;
        }
    }
    return true;
}

std::array<double, 16> matrix4x4_multiply(const std::array<double, 16>& left, const std::array<double, 16>& right) {
    std::array<double, 16> result{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            double value = 0.0;
            for (int inner = 0; inner < 4; ++inner) {
                value += left[static_cast<std::size_t>(row * 4 + inner)]
                    * right[static_cast<std::size_t>(inner * 4 + column)];
            }
            result[static_cast<std::size_t>(row * 4 + column)] = value;
        }
    }
    return result;
}

bool matrix4x4_from_transform_json(const JsonValue& item, std::array<double, 16>& matrix) {
    return matrix4x4_from_json(item.get("world_transform"), matrix)
        || matrix4x4_from_json(item.get("transform"), matrix)
        || matrix4x4_from_json(item.get("matrix"), matrix);
}

Vec3 vec3_or(const JsonValue* value, const Vec3& fallback) {
    if (value == nullptr) {
        return fallback;
    }
    if (value->type == JsonValue::Type::Object) {
        return {
            number_or(value->get("x"), fallback[0]),
            number_or(value->get("y"), fallback[1]),
            number_or(value->get("z"), fallback[2]),
        };
    }
    if (value->type != JsonValue::Type::Array || value->array_value.size() < 3) {
        return fallback;
    }
    return {
        number_or(&value->array_value[0], fallback[0]),
        number_or(&value->array_value[1], fallback[1]),
        number_or(&value->array_value[2], fallback[2]),
    };
}

Vec2 vec2_or(const JsonValue* value, const Vec2& fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() < 2) {
        return fallback;
    }
    return {
        number_or(&value->array_value[0], fallback[0]),
        number_or(&value->array_value[1], fallback[1]),
    };
}

double degrees_to_radians(double degrees) {
    return degrees * 3.14159265358979323846 / 180.0;
}
