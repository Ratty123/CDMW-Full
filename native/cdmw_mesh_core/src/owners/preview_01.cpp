void append_f32_le(std::vector<char>& out, double value) {
    const float raw = static_cast<float>(std::isfinite(value) ? value : 0.0);
    std::uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(raw), "float size must be 32-bit");
    std::memcpy(&bits, &raw, sizeof(bits));
    out.push_back(static_cast<char>(bits & 0xffu));
    out.push_back(static_cast<char>((bits >> 8) & 0xffu));
    out.push_back(static_cast<char>((bits >> 16) & 0xffu));
    out.push_back(static_cast<char>((bits >> 24) & 0xffu));
}

Vec3 cross_vec3(const Vec3& left, const Vec3& right) {
    return {
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    };
}

Vec3 sanitize_normal_for_preview(const Vec3& value, bool* repaired = nullptr) {
    const double length = std::sqrt(dot_vec3(value, value));
    if (length > 1e-8 && std::isfinite(length)) {
        if (repaired != nullptr) {
            *repaired = false;
        }
        return {value[0] / length, value[1] / length, value[2] / length};
    }
    if (repaired != nullptr) {
        *repaired = true;
    }
    return {0.0, 0.0, 1.0};
}

void orthogonal_tangent_frame_for_preview(const Vec3& normal_value, Vec3& tangent, Vec3& bitangent) {
    Vec3 normal = sanitize_normal_for_preview(normal_value);
    const Vec3 seed = std::abs(normal[2]) < 0.999 ? Vec3{0.0, 0.0, 1.0} : Vec3{1.0, 0.0, 0.0};
    tangent = normalized_vec3(cross_vec3(seed, normal), {1.0, 0.0, 0.0});
    bitangent = normalized_vec3(cross_vec3(normal, tangent), {0.0, 1.0, 0.0});
}

std::vector<int> valid_triangle_indices_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<int> result;
    const std::vector<int> indices = int_vector_from_json(value);
    result.reserve(indices.size());
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = indices[offset];
        const int b = indices[offset + 1];
        const int c = indices[offset + 2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.push_back(a);
        result.push_back(b);
        result.push_back(c);
    }
    return result;
}

struct PreviewTriangleIndexStream {
    std::vector<int> flat_indices;
    std::vector<int> face_ordinals;
};

PreviewTriangleIndexStream preview_triangle_index_stream_from_json(const JsonValue* value, std::size_t vertex_count) {
    PreviewTriangleIndexStream result;
    const std::vector<int> indices = int_vector_from_json(value);
    result.flat_indices.reserve(indices.size());
    result.face_ordinals.reserve(indices.size() / 3);
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = indices[offset];
        const int b = indices[offset + 1];
        const int c = indices[offset + 2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.flat_indices.push_back(a);
        result.flat_indices.push_back(b);
        result.flat_indices.push_back(c);
        result.face_ordinals.push_back(static_cast<int>(offset / 3));
    }
    return result;
}

PreviewTriangleIndexStream preview_triangle_index_stream_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    PreviewTriangleIndexStream result;
    const std::vector<int> indices = int_vector_from_binary_or_json(item, "indices_binary", "indices");
    result.flat_indices.reserve(indices.size());
    result.face_ordinals.reserve(indices.size() / 3);
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = indices[offset];
        const int b = indices[offset + 1];
        const int c = indices[offset + 2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.flat_indices.push_back(a);
        result.flat_indices.push_back(b);
        result.flat_indices.push_back(c);
        result.face_ordinals.push_back(static_cast<int>(offset / 3));
    }
    return result;
}

PreviewTriangleIndexStream preview_triangle_index_stream_from_faces_json(const JsonValue* value, std::size_t vertex_count) {
    PreviewTriangleIndexStream result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.flat_indices.reserve(value->array_value.size() * 3u);
    result.face_ordinals.reserve(value->array_value.size());
    for (std::size_t face_index = 0; face_index < value->array_value.size(); ++face_index) {
        const JsonValue& face = value->array_value[face_index];
        if (face.type != JsonValue::Type::Array || face.array_value.size() < 3) {
            continue;
        }
        const int a = int_or(&face.array_value[0], -1);
        const int b = int_or(&face.array_value[1], -1);
        const int c = int_or(&face.array_value[2], -1);
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.flat_indices.push_back(a);
        result.flat_indices.push_back(b);
        result.flat_indices.push_back(c);
        result.face_ordinals.push_back(static_cast<int>(face_index));
    }
    return result;
}

PreviewTriangleIndexStream preview_triangle_index_stream_from_faces(const std::vector<std::array<int, 3>>& faces) {
    PreviewTriangleIndexStream result;
    result.flat_indices.reserve(faces.size() * 3u);
    result.face_ordinals.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const std::array<int, 3>& face = faces[face_index];
        result.flat_indices.push_back(face[0]);
        result.flat_indices.push_back(face[1]);
        result.flat_indices.push_back(face[2]);
        result.face_ordinals.push_back(static_cast<int>(face_index));
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_flat_indices(const std::vector<int>& indices) {
    std::vector<std::array<int, 3>> faces;
    faces.reserve(indices.size() / 3);
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        faces.push_back({indices[offset], indices[offset + 1], indices[offset + 2]});
    }
    return faces;
}

struct PreviewSmoothNormalsResult {
    std::vector<Vec3> normals;
    double changed_ratio = 0.0;
};

std::array<long long, 3> preview_smooth_position_key(const Vec3& position) {
    return {
        static_cast<long long>(std::llround(position[0] * 100000.0)),
        static_cast<long long>(std::llround(position[1] * 100000.0)),
        static_cast<long long>(std::llround(position[2] * 100000.0)),
    };
}

PreviewSmoothNormalsResult build_preview_smoothed_normals(
    const std::vector<Vec3>& positions,
    const std::vector<Vec3>& normals,
    const std::vector<int>& flat_indices
) {
    PreviewSmoothNormalsResult result;
    result.normals = normals;
    const std::size_t vertex_count = positions.size();
    if (vertex_count == 0 || normals.size() != vertex_count) {
        return result;
    }
    std::map<std::array<long long, 3>, Vec3> accum_by_position;
    for (std::size_t offset = 0; offset + 2 < flat_indices.size(); offset += 3) {
        const int a = flat_indices[offset];
        const int b = flat_indices[offset + 1];
        const int c = flat_indices[offset + 2];
        const Vec3 ab = sub_vec3(positions[static_cast<std::size_t>(b)], positions[static_cast<std::size_t>(a)]);
        const Vec3 ac = sub_vec3(positions[static_cast<std::size_t>(c)], positions[static_cast<std::size_t>(a)]);
        const Vec3 face = cross_vec3(ab, ac);
        const double length = length_vec3(face);
        if (length <= 1e-12 || !std::isfinite(length)) {
            continue;
        }
        for (const int index : {a, b, c}) {
            Vec3& accum = accum_by_position[preview_smooth_position_key(positions[static_cast<std::size_t>(index)])];
            accum = add_vec3(accum, face);
        }
    }

    int changed = 0;
    for (std::size_t index = 0; index < vertex_count; ++index) {
        const Vec3 original = normals[index];
        const auto found = accum_by_position.find(preview_smooth_position_key(positions[index]));
        if (found == accum_by_position.end()) {
            result.normals[index] = original;
            continue;
        }
        bool repaired = false;
        const Vec3 candidate = sanitize_normal_for_preview(found->second, &repaired);
        if (repaired) {
            result.normals[index] = original;
            continue;
        }
        const double dot = dot_vec3(original, candidate);
        if (dot <= 0.05) {
            result.normals[index] = original;
            continue;
        }
        if (dot < 0.995) {
            ++changed;
        }
        result.normals[index] = candidate;
    }
    result.changed_ratio = static_cast<double>(changed) / static_cast<double>(std::max<std::size_t>(1, vertex_count));
    return result;
}

struct PreviewTangentFrames {
    std::vector<Vec3> tangents;
    std::vector<Vec3> bitangents;
    std::vector<bool> tangent_valid;
    std::vector<bool> bitangent_valid;
};

PreviewTangentFrames build_preview_tangent_frames(
    const std::vector<Vec3>& positions,
    const std::vector<Vec2>& uvs,
    const std::vector<Vec3>& normals,
    const std::vector<int>& flat_indices
) {
    const std::size_t vertex_count = positions.size();
    PreviewTangentFrames result;
    result.tangents.resize(vertex_count, {1.0, 0.0, 0.0});
    result.bitangents.resize(vertex_count, {0.0, 1.0, 0.0});
    result.tangent_valid.resize(vertex_count, false);
    result.bitangent_valid.resize(vertex_count, false);
    if (vertex_count == 0 || uvs.size() != vertex_count || normals.size() != vertex_count) {
        for (std::size_t index = 0; index < vertex_count; ++index) {
            orthogonal_tangent_frame_for_preview(normals.size() == vertex_count ? normals[index] : Vec3{0.0, 0.0, 1.0}, result.tangents[index], result.bitangents[index]);
        }
        return result;
    }

    std::vector<Vec3> tangent_accum(vertex_count, {0.0, 0.0, 0.0});
    std::vector<Vec3> bitangent_accum(vertex_count, {0.0, 0.0, 0.0});
    for (std::size_t offset = 0; offset + 2 < flat_indices.size(); offset += 3) {
        const int a = flat_indices[offset];
        const int b = flat_indices[offset + 1];
        const int c = flat_indices[offset + 2];
        const Vec3 edge1 = sub_vec3(positions[static_cast<std::size_t>(b)], positions[static_cast<std::size_t>(a)]);
        const Vec3 edge2 = sub_vec3(positions[static_cast<std::size_t>(c)], positions[static_cast<std::size_t>(a)]);
        const Vec2 uv0 = uvs[static_cast<std::size_t>(a)];
        const Vec2 uv1 = uvs[static_cast<std::size_t>(b)];
        const Vec2 uv2 = uvs[static_cast<std::size_t>(c)];
        const double du1 = uv1[0] - uv0[0];
        const double dv1 = uv1[1] - uv0[1];
        const double du2 = uv2[0] - uv0[0];
        const double dv2 = uv2[1] - uv0[1];
        const double determinant = du1 * dv2 - dv1 * du2;
        if (std::abs(determinant) <= 1e-8 || !std::isfinite(determinant)) {
            continue;
        }
        const double reciprocal = 1.0 / determinant;
        const Vec3 tangent = {
            reciprocal * ((dv2 * edge1[0]) - (dv1 * edge2[0])),
            reciprocal * ((dv2 * edge1[1]) - (dv1 * edge2[1])),
            reciprocal * ((dv2 * edge1[2]) - (dv1 * edge2[2])),
        };
        const Vec3 bitangent = {
            reciprocal * ((-du2 * edge1[0]) + (du1 * edge2[0])),
            reciprocal * ((-du2 * edge1[1]) + (du1 * edge2[1])),
            reciprocal * ((-du2 * edge1[2]) + (du1 * edge2[2])),
        };
        const double tangent_length = length_vec3(tangent);
        const double bitangent_length = length_vec3(bitangent);
        if (tangent_length <= 1e-8 || bitangent_length <= 1e-8 || !std::isfinite(tangent_length) || !std::isfinite(bitangent_length)) {
            continue;
        }
        for (const int vertex_index : {a, b, c}) {
            const std::size_t target = static_cast<std::size_t>(vertex_index);
            tangent_accum[target] = add_vec3(tangent_accum[target], tangent);
            bitangent_accum[target] = add_vec3(bitangent_accum[target], bitangent);
            result.tangent_valid[target] = true;
            result.bitangent_valid[target] = true;
        }
    }

    for (std::size_t index = 0; index < vertex_count; ++index) {
        const Vec3 normal = normals[index];
        Vec3 tangent;
        Vec3 bitangent;
        orthogonal_tangent_frame_for_preview(normal, tangent, bitangent);
        double tangent_length = length_vec3(tangent_accum[index]);
        if (tangent_length <= 1e-6 || !std::isfinite(tangent_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.tangent_valid[index] = false;
            result.bitangent_valid[index] = false;
            continue;
        }
        Vec3 projected_tangent = scale_vec3(tangent_accum[index], 1.0 / tangent_length);
        projected_tangent = sub_vec3(projected_tangent, scale_vec3(normal, dot_vec3(normal, projected_tangent)));
        tangent_length = length_vec3(projected_tangent);
        if (tangent_length <= 1e-6 || !std::isfinite(tangent_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.tangent_valid[index] = false;
            result.bitangent_valid[index] = false;
            continue;
        }
        tangent = scale_vec3(projected_tangent, 1.0 / tangent_length);
        Vec3 raw_bitangent = bitangent_accum[index];
        if (dot_vec3(raw_bitangent, raw_bitangent) <= 1e-6) {
            raw_bitangent = cross_vec3(normal, tangent);
            result.bitangent_valid[index] = false;
        }
        const double raw_bitangent_length = length_vec3(raw_bitangent);
        if (raw_bitangent_length <= 1e-6 || !std::isfinite(raw_bitangent_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.bitangent_valid[index] = false;
            continue;
        }
        Vec3 cross_bitangent = cross_vec3(normal, tangent);
        const double cross_length = length_vec3(cross_bitangent);
        if (cross_length <= 1e-6 || !std::isfinite(cross_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.bitangent_valid[index] = false;
            continue;
        }
        cross_bitangent = scale_vec3(cross_bitangent, 1.0 / cross_length);
        const double handedness = dot_vec3(cross_bitangent, raw_bitangent) < 0.0 ? -1.0 : 1.0;
        result.tangents[index] = tangent;
        result.bitangents[index] = scale_vec3(cross_bitangent, handedness);
    }
    return result;
}

int count_false_values(const std::vector<bool>& values) {
    int count = 0;
    for (bool value : values) {
        if (!value) {
            ++count;
        }
    }
    return count;
}

struct PreviewGeometryBatchReport {
    int mesh_index = -1;
    int first_vertex = 0;
    int vertex_count = 0;
    Vec3 bounds_min{0.0, 0.0, 0.0};
    Vec3 bounds_max{0.0, 0.0, 0.0};
    Vec3 base_color{1.0, 1.0, 1.0};
    bool has_texture_coordinates = false;
    bool texture_wrap_repeat = false;
    bool tangents_usable = false;
    double normal_finite_ratio = 1.0;
    int normal_repair_count = 0;
    double tangent_finite_ratio = 1.0;
    double bitangent_finite_ratio = 1.0;
    double uv_finite_ratio = 0.0;
    double smooth_normal_ratio = 0.0;
    double position_y_min = 0.0;
    double position_y_max = 0.0;
    std::vector<int> source_vertex_indices;
    std::vector<int> source_face_indices;
    int identity_offset = 0;
    int identity_size = 0;
};

struct PreviewModelMeshReport {
    int parsed_submesh_index = -1;
    int source_submesh_index = -1;
    std::vector<Vec3> positions;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    std::vector<int> indices;
    std::vector<int> source_vertex_indices;
    std::vector<int> source_face_indices;
    std::string positions_path;
    std::string uvs_path;
    std::string normals_path;
    std::string indices_path;
    std::string source_vertex_indices_path;
    std::string source_face_indices_path;
};

bool finite_vec2(const Vec2& value) {
    return std::isfinite(value[0]) && std::isfinite(value[1]);
}

bool finite_vec3(const Vec3& value) {
    return std::isfinite(value[0]) && std::isfinite(value[1]) && std::isfinite(value[2]);
}

bool preview_vertex_tangent_usable(const Vec3& normal, const Vec2& uv, const Vec3& tangent, const Vec3& bitangent) {
    return finite_vec3(normal)
        && finite_vec2(uv)
        && finite_vec3(tangent)
        && finite_vec3(bitangent)
        && length_vec3(normal) > 0.05
        && length_vec3(tangent) > 0.05
        && length_vec3(bitangent) > 0.05;
}

void append_preview_vertex(
    std::vector<char>& geometry,
    const Vec3& position,
    const Vec3& normal,
    const Vec3& color,
    const Vec2& uv,
    const Vec3& tangent,
    const Vec3& bitangent,
    const Vec3& smooth_normal,
    const Vec3& barycentric
) {
    append_f32_le(geometry, position[0]);
    append_f32_le(geometry, position[1]);
    append_f32_le(geometry, position[2]);
    append_f32_le(geometry, normal[0]);
    append_f32_le(geometry, normal[1]);
    append_f32_le(geometry, normal[2]);
    append_f32_le(geometry, color[0]);
    append_f32_le(geometry, color[1]);
    append_f32_le(geometry, color[2]);
    append_f32_le(geometry, uv[0]);
    append_f32_le(geometry, uv[1]);
    append_f32_le(geometry, tangent[0]);
    append_f32_le(geometry, tangent[1]);
    append_f32_le(geometry, tangent[2]);
    append_f32_le(geometry, bitangent[0]);
    append_f32_le(geometry, bitangent[1]);
    append_f32_le(geometry, bitangent[2]);
    append_f32_le(geometry, smooth_normal[0]);
    append_f32_le(geometry, smooth_normal[1]);
    append_f32_le(geometry, smooth_normal[2]);
    append_f32_le(geometry, barycentric[0]);
    append_f32_le(geometry, barycentric[1]);
    append_f32_le(geometry, barycentric[2]);
}

std::string preview_geometry_report_json(
    const std::vector<PreviewGeometryBatchReport>& batches,
    int vertex_count,
    int geometry_size,
    const std::string& output_path = std::string()
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_geometry\""
        << ",\"vertex_stride_bytes\":92"
        << ",\"vertex_count\":" << vertex_count
        << ",\"geometry_size\":" << geometry_size
        << ",\"batches\":[";
    for (std::size_t i = 0; i < batches.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const PreviewGeometryBatchReport& batch = batches[i];
        out << "{\"mesh_index\":" << batch.mesh_index
            << ",\"first_vertex\":" << batch.first_vertex
            << ",\"vertex_count\":" << batch.vertex_count
            << ",\"bounds_min\":";
        write_vec3(out, batch.bounds_min);
        out << ",\"bounds_max\":";
        write_vec3(out, batch.bounds_max);
        out << ",\"base_color\":";
        write_vec3(out, batch.base_color);
        out << ",\"tangents_usable\":" << (batch.tangents_usable ? "true" : "false")
            << ",\"has_texture_coordinates\":" << (batch.has_texture_coordinates ? "true" : "false")
            << ",\"texture_wrap_repeat\":" << (batch.texture_wrap_repeat ? "true" : "false")
            << ",\"normal_finite_ratio\":" << std::setprecision(17) << batch.normal_finite_ratio
            << ",\"normal_repair_count\":" << batch.normal_repair_count
            << ",\"tangent_finite_ratio\":" << batch.tangent_finite_ratio
            << ",\"bitangent_finite_ratio\":" << batch.bitangent_finite_ratio
            << ",\"uv_finite_ratio\":" << batch.uv_finite_ratio
            << ",\"smooth_normal_ratio\":" << batch.smooth_normal_ratio
            << ",\"position_y_min\":" << batch.position_y_min
            << ",\"position_y_max\":" << batch.position_y_max;
        int source_vertex_start = -1;
        if (contiguous_int_range(batch.source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << batch.source_vertex_indices.size();
        } else if (!output_path.empty() && !batch.source_vertex_indices.empty()) {
            const std::string source_vertices_path = sibling_binary_path(
                output_path,
                ".batch_" + std::to_string(i) + ".source_vertices.bin");
            write_int_binary_file(source_vertices_path, batch.source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_int_binary_descriptor(out, source_vertices_path, batch.source_vertex_indices.size(), 1);
        } else {
            out << ",\"source_vertex_indices\":";
            write_int_vector(out, batch.source_vertex_indices);
        }
        int source_face_start = -1;
        if (contiguous_int_range(batch.source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << batch.source_face_indices.size();
        } else if (!output_path.empty() && !batch.source_face_indices.empty()) {
            const std::string source_faces_path = sibling_binary_path(
                output_path,
                ".batch_" + std::to_string(i) + ".source_faces.bin");
            write_int_binary_file(source_faces_path, batch.source_face_indices);
            out << ",\"source_face_indices_binary\":";
            write_int_binary_descriptor(out, source_faces_path, batch.source_face_indices.size(), 1);
        } else {
            out << ",\"source_face_indices\":";
            write_int_vector(out, batch.source_face_indices);
        }
        out << ",\"identity_offset\":" << batch.identity_offset
            << ",\"identity_size\":" << batch.identity_size
            << "}";
    }
    out << "]}";
    return out.str();
}

void write_vec3_vector(std::ostream& out, const std::vector<Vec3>& values) {
    out << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        write_vec3(out, values[index]);
    }
    out << ']';
}

void write_vec2_vector(std::ostream& out, const std::vector<Vec2>& values) {
    out << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        write_vec2(out, values[index]);
    }
    out << ']';
}

std::string preview_model_report_json(
    const std::vector<PreviewModelMeshReport>& meshes,
    int vertex_count,
    int face_count
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_model\""
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"mesh_count\":" << meshes.size()
        << ",\"meshes\":[";
    for (std::size_t mesh_index = 0; mesh_index < meshes.size(); ++mesh_index) {
        if (mesh_index > 0) {
            out << ',';
        }
        const PreviewModelMeshReport& mesh = meshes[mesh_index];
        out << "{\"parsed_submesh_index\":" << mesh.parsed_submesh_index
            << ",\"source_submesh_index\":" << mesh.source_submesh_index
            << ",\"vertex_count\":" << mesh.positions.size()
            << ",\"face_count\":" << mesh.indices.size() / 3u;
        if (!mesh.positions_path.empty()) {
            write_vec3_binary_file(mesh.positions_path, mesh.positions);
            out << ",\"positions_binary\":";
            write_vec3_binary_descriptor(out, mesh.positions_path, mesh.positions.size());
        } else {
            out << ",\"positions\":";
            write_vec3_vector(out, mesh.positions);
        }
        if (!mesh.uvs_path.empty()) {
            write_vec2_binary_file(mesh.uvs_path, mesh.uvs);
            out << ",\"texture_coordinates_binary\":";
            write_vec2_binary_descriptor(out, mesh.uvs_path, mesh.uvs.size());
        } else {
            out << ",\"texture_coordinates\":";
            write_vec2_vector(out, mesh.uvs);
        }
        if (!mesh.normals_path.empty()) {
            write_vec3_binary_file(mesh.normals_path, mesh.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, mesh.normals_path, mesh.normals.size());
        } else {
            out << ",\"normals\":";
            write_vec3_vector(out, mesh.normals);
        }
        if (!mesh.indices_path.empty()) {
            write_int_binary_file(mesh.indices_path, mesh.indices);
            out << ",\"indices_binary\":";
            write_int_binary_descriptor(out, mesh.indices_path, mesh.indices.size(), 1);
        } else {
            out << ",\"indices\":";
            write_int_vector(out, mesh.indices);
        }
        int source_vertex_start = -1;
        if (contiguous_int_range(mesh.source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << mesh.source_vertex_indices.size();
        } else if (!mesh.source_vertex_indices_path.empty()) {
            write_int_binary_file(mesh.source_vertex_indices_path, mesh.source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_int_binary_descriptor(out, mesh.source_vertex_indices_path, mesh.source_vertex_indices.size(), 1);
        } else {
            out << ",\"source_vertex_indices\":";
            write_int_vector(out, mesh.source_vertex_indices);
        }
        int source_face_start = -1;
        if (contiguous_int_range(mesh.source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << mesh.source_face_indices.size();
        } else if (!mesh.source_face_indices_path.empty()) {
            write_int_binary_file(mesh.source_face_indices_path, mesh.source_face_indices);
            out << ",\"source_face_indices_binary\":";
            write_int_binary_descriptor(out, mesh.source_face_indices_path, mesh.source_face_indices.size(), 1);
        } else {
            out << ",\"source_face_indices\":";
            write_int_vector(out, mesh.source_face_indices);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string run_preview_model(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const Vec3 center = vec3_or(root.get("normalization_center"), {0.0, 0.0, 0.0});
    double scale = number_or(root.get("normalization_scale"), 1.0);
    if (std::abs(scale) <= 1e-12 || !std::isfinite(scale)) {
        scale = 1.0;
    }
    std::vector<PreviewModelMeshReport> reports;
    int vertex_count = 0;
    int face_count = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int parsed_submesh_index = int_or(item.get("index"), -1);
        const int source_submesh_index = int_or(item.get("source_submesh_index"), parsed_submesh_index);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        if (parsed_submesh_index < 0 || vertices.empty()) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const PreviewTriangleIndexStream triangle_stream = preview_triangle_index_stream_from_faces(faces);
        if (triangle_stream.flat_indices.empty()) {
            continue;
        }
        const std::vector<int> source_vertices = mesh_source_vertex_indices_from_item(item, vertices.size());
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        PreviewModelMeshReport report;
        report.parsed_submesh_index = parsed_submesh_index;
        report.source_submesh_index = source_submesh_index;
        report.positions_path = string_or(item.get("positions_output_path"), "");
        report.uvs_path = string_or(item.get("texture_coordinates_output_path"), "");
        report.normals_path = string_or(item.get("normals_output_path"), "");
        report.indices_path = string_or(item.get("indices_output_path"), "");
        report.source_vertex_indices_path = string_or(item.get("source_vertex_indices_output_path"), "");
        report.source_face_indices_path = string_or(item.get("source_face_indices_output_path"), "");
        report.positions.reserve(vertices.size());
        for (const Vec3& vertex : vertices) {
            report.positions.push_back({
                (vertex[0] - center[0]) * scale,
                (vertex[1] - center[1]) * scale,
                (vertex[2] - center[2]) * scale,
            });
        }
        report.uvs = mesh_uvs_from_item(item);
        if (report.uvs.size() > report.positions.size()) {
            report.uvs.resize(report.positions.size());
        }
        report.normals = mesh_normals_from_item(item);
        if (report.normals.size() > report.positions.size()) {
            report.normals.resize(report.positions.size());
        }
        report.indices = triangle_stream.flat_indices;
        report.source_vertex_indices.reserve(vertices.size());
        for (std::size_t index = 0; index < vertices.size(); ++index) {
            const int source_vertex_index = index < source_vertices.size()
                ? source_vertices[index]
                : static_cast<int>(index);
            report.source_vertex_indices.push_back(source_vertex_index);
        }
        report.source_face_indices.reserve(triangle_stream.face_ordinals.size());
        for (const int face_ordinal : triangle_stream.face_ordinals) {
            const int source_face_index = face_ordinal >= 0 && static_cast<std::size_t>(face_ordinal) < source_faces.size()
                ? source_faces[static_cast<std::size_t>(face_ordinal)]
                : face_ordinal;
            report.source_face_indices.push_back(source_face_index);
        }
        vertex_count += static_cast<int>(report.positions.size());
        face_count += static_cast<int>(report.indices.size() / 3u);
        reports.push_back(std::move(report));
    }
    return preview_model_report_json(reports, vertex_count, face_count);
}
