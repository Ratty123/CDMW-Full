BoneAssignments copy_bones_by_vertex_remap(const BoneAssignments& input, const std::vector<int>& remap) {
    if (!valid_bone_assignments(input) || input.indices.empty() || input.indices.size() != input.weights.size()) {
        return {};
    }
    BoneAssignments output;
    output.indices.reserve(remap.size());
    output.weights.reserve(remap.size());
    for (const int old_index : remap) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= input.indices.size()) {
            return {};
        }
        output.indices.push_back(input.indices[static_cast<std::size_t>(old_index)]);
        output.weights.push_back(input.weights[static_cast<std::size_t>(old_index)]);
    }
    return output;
}

struct CleanupTopology {
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::vector<int> index_map;
    int merged_vertices = 0;
    int degenerate_faces = 0;
    int duplicate_faces = 0;
};

CleanupTopology build_cleanup_topology(
    std::vector<Vec3> vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::set<int>& selected,
    double threshold_squared
) {
    std::vector<int> remap(vertices.size(), 0);
    for (std::size_t i = 0; i < remap.size(); ++i) remap[i] = static_cast<int>(i);
    int merged_vertices = 0;
    for (const int keeper : selected) {
        if (remap[static_cast<std::size_t>(keeper)] != keeper) continue;
        std::vector<int> cluster{keeper};
        for (const int candidate : selected) {
            if (candidate <= keeper || remap[static_cast<std::size_t>(candidate)] != candidate) continue;
            if (distance_squared_vec3(
                    vertices[static_cast<std::size_t>(keeper)],
                    vertices[static_cast<std::size_t>(candidate)]) <= threshold_squared) {
                cluster.push_back(candidate);
            }
        }
        if (cluster.size() < 2) continue;
        vertices[static_cast<std::size_t>(keeper)] = average_vertices(vertices, cluster);
        for (std::size_t cluster_index = 1; cluster_index < cluster.size(); ++cluster_index) {
            remap[static_cast<std::size_t>(cluster[cluster_index])] = keeper;
            ++merged_vertices;
        }
    }
    std::set<std::array<int, 3>> seen_faces;
    std::vector<std::array<int, 3>> kept_faces;
    int degenerate_faces = 0;
    int duplicate_faces = 0;
    for (const auto& face : faces) {
        const std::array<int, 3> remapped{
            remap[static_cast<std::size_t>(face[0])],
            remap[static_cast<std::size_t>(face[1])],
            remap[static_cast<std::size_t>(face[2])],
        };
        if (remapped[0] == remapped[1] || remapped[1] == remapped[2] || remapped[0] == remapped[2]) {
            ++degenerate_faces;
        } else if (!seen_faces.insert(remapped).second) {
            ++duplicate_faces;
        } else {
            kept_faces.push_back(remapped);
        }
    }
    std::set<int> used_vertices;
    for (const auto& face : kept_faces) used_vertices.insert(face.begin(), face.end());
    std::map<int, int> compacted_by_old;
    std::vector<Vec3> compacted_vertices;
    for (const int old_index : used_vertices) {
        compacted_by_old[old_index] = static_cast<int>(compacted_vertices.size());
        compacted_vertices.push_back(vertices[static_cast<std::size_t>(old_index)]);
    }
    std::vector<std::array<int, 3>> compacted_faces;
    for (const auto& face : kept_faces) {
        compacted_faces.push_back({compacted_by_old[face[0]], compacted_by_old[face[1]], compacted_by_old[face[2]]});
    }
    std::vector<int> index_map(vertices.size(), -1);
    for (std::size_t old_index = 0; old_index < vertices.size(); ++old_index) {
        if (remap[old_index] != static_cast<int>(old_index)) continue;
        const auto found = compacted_by_old.find(static_cast<int>(old_index));
        if (found != compacted_by_old.end()) index_map[old_index] = found->second;
    }
    return {
        std::move(compacted_vertices), std::move(compacted_faces), std::move(index_map),
        merged_vertices, degenerate_faces, duplicate_faces,
    };
}

std::vector<SubmeshCleanupResult> run_cleanup(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    double threshold = 1e-5;
    const JsonValue* cleanup = root.get("cleanup");
    if (cleanup != nullptr && cleanup->type == JsonValue::Type::Object) {
        threshold = number_or(cleanup->get("threshold"), threshold);
    }
    if (!std::isfinite(threshold) || threshold <= 0.0) {
        threshold = 1e-5;
    }
    const double threshold_squared = threshold * threshold;
    std::vector<SubmeshCleanupResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::set<int> selected = selected_vertices_from_binary_or_json(item, vertices.size());
        if (index < 0 || vertices.empty() || selected.size() < 2) {
            continue;
        }
        const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
        const std::string faces_path = string_or(item.get("faces_output_path"), "");
        const std::string index_map_path = string_or(item.get("index_map_output_path"), "");
        const std::string normals_path = string_or(item.get("normals_output_path"), "");
        const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
        const std::string tangents_path = string_or(item.get("tangents_output_path"), "");
        const std::string tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        const std::string bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        const std::string bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        const std::string bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        const std::string source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        const std::string source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        const bool suppress_index_map_report = bool_or(item.get("suppress_index_map_report"), false);

        CleanupTopology cleaned = build_cleanup_topology(std::move(vertices), faces, selected, threshold_squared);
        const int removed_vertices = static_cast<int>(cleaned.index_map.size()) - static_cast<int>(cleaned.vertices.size());
        const int removed_faces = static_cast<int>(faces.size()) - static_cast<int>(cleaned.faces.size());
        if (cleaned.merged_vertices <= 0 && removed_vertices <= 0 && removed_faces <= 0) {
            continue;
        }
        SubmeshCleanupResult result;
        result.index = index;
        result.vertices_path = vertices_path;
        result.faces_path = faces_path;
        result.index_map_path = index_map_path;
        result.normals_path = normals_path;
        result.uvs_path = uvs_path;
        result.tangents_path = tangents_path;
        result.tangent_signs_path = tangent_signs_path;
        result.bone_counts_path = bone_counts_path;
        result.bone_indices_path = bone_indices_path;
        result.bone_weights_path = bone_weights_path;
        result.source_vertex_map_path = source_vertex_map_path;
        result.source_vertex_offsets_path = source_vertex_offsets_path;
        result.vertices = std::move(cleaned.vertices);
        result.faces = std::move(cleaned.faces);
        result.index_map = std::move(cleaned.index_map);
        if (!result.normals_path.empty()) {
            result.normals = compute_smooth_normals(result.vertices, result.faces);
        }
        if (!result.uvs_path.empty()) {
            result.uvs = remap_vec2_by_index_map(mesh_uvs_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.tangents_path.empty()) {
            result.tangents = remap_vec3_by_index_map(mesh_tangents_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.tangent_signs_path.empty()) {
            result.tangent_signs = remap_double_by_index_map(mesh_tangent_signs_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.bone_counts_path.empty() && !result.bone_indices_path.empty() && !result.bone_weights_path.empty()) {
            result.bones = remap_bones_by_index_map(mesh_bones_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.source_vertex_map_path.empty()) {
            std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
                item,
                "source_vertex_map_binary",
                "source_vertex_map",
                "source_vertex_map_start",
                "source_vertex_map_count"
            );
            if (source_vertex_map.empty()) {
                if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                    source_vertex_map = session->source_vertex_map;
                }
            }
            result.source_vertex_map = remap_int_by_index_map(
                source_vertex_map,
                result.index_map,
                result.vertices.size());
        }
        if (!result.source_vertex_offsets_path.empty()) {
            std::vector<int> source_vertex_offsets = source_vertex_offsets_from_item(item);
            if (source_vertex_offsets.empty()) {
                if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                    source_vertex_offsets = session->source_vertex_offsets;
                }
            }
            result.source_vertex_offsets = remap_int_by_index_map(
                source_vertex_offsets,
                result.index_map,
                result.vertices.size());
        }
        result.removed_vertices = removed_vertices;
        result.removed_faces = removed_faces;
        result.merged_vertices = cleaned.merged_vertices;
        result.degenerate_faces = cleaned.degenerate_faces;
        result.duplicate_faces = cleaned.duplicate_faces;
        result.suppress_index_map_report = suppress_index_map_report;
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            session->vertices = result.vertices;
            session->faces = result.faces;
            session->source_face_indices = identity_indices(session->faces.size());
            session->normals = result.normals.size() == result.vertices.size() ? result.normals : std::vector<Vec3>();
            session->uvs = result.uvs.size() == result.vertices.size() ? result.uvs : std::vector<Vec2>();
            session->tangents = result.tangents.size() == result.vertices.size() ? result.tangents : std::vector<Vec3>();
            session->tangent_signs = result.tangent_signs.size() == result.vertices.size() ? result.tangent_signs : std::vector<double>();
            if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
                session->bone_indices = result.bones.indices;
                session->bone_weights = result.bones.weights;
            } else {
                session->bone_indices.clear();
                session->bone_weights.clear();
            }
            session->source_vertex_map = result.source_vertex_map.size() == result.vertices.size() ? result.source_vertex_map : std::vector<int>();
            session->source_vertex_offsets = result.source_vertex_offsets.size() == result.vertices.size() ? result.source_vertex_offsets : std::vector<int>();
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<float> meshopt_positions_from_vertices(const std::vector<Vec3>& vertices) {
    std::vector<float> positions;
    positions.reserve(vertices.size() * 3);
    for (const Vec3& vertex : vertices) {
        positions.push_back(static_cast<float>(vertex[0]));
        positions.push_back(static_cast<float>(vertex[1]));
        positions.push_back(static_cast<float>(vertex[2]));
    }
    return positions;
}

std::vector<unsigned int> meshopt_indices_from_faces(const std::vector<std::array<int, 3>>& faces) {
    std::vector<unsigned int> indices;
    indices.reserve(faces.size() * 3);
    for (const auto& face : faces) {
        indices.push_back(static_cast<unsigned int>(face[0]));
        indices.push_back(static_cast<unsigned int>(face[1]));
        indices.push_back(static_cast<unsigned int>(face[2]));
    }
    return indices;
}

std::vector<std::array<int, 3>> faces_from_meshopt_indices(const std::vector<unsigned int>& indices) {
    std::vector<std::array<int, 3>> faces;
    faces.reserve(indices.size() / 3);
    for (std::size_t i = 0; i + 2 < indices.size(); i += 3) {
        faces.push_back({
            static_cast<int>(indices[i]),
            static_cast<int>(indices[i + 1]),
            static_cast<int>(indices[i + 2]),
        });
    }
    return faces;
}

OptimizationStats meshopt_stats(
    const std::vector<unsigned int>& indices,
    const std::vector<float>& positions,
    std::size_t vertex_count
) {
    OptimizationStats stats;
    if (indices.empty() || vertex_count == 0 || positions.empty()) {
        return stats;
    }
    const meshopt_VertexCacheStatistics cache = meshopt_analyzeVertexCache(indices.data(), indices.size(), vertex_count, 16, 32, 0);
    const meshopt_OverdrawStatistics overdraw = meshopt_analyzeOverdraw(indices.data(), indices.size(), positions.data(), vertex_count, sizeof(float) * 3);
    const meshopt_VertexFetchStatistics fetch = meshopt_analyzeVertexFetch(indices.data(), indices.size(), vertex_count, sizeof(float) * 3);
    stats.cache_acmr = cache.acmr;
    stats.cache_atvr = cache.atvr;
    stats.overdraw = overdraw.overdraw;
    stats.overfetch = fetch.overfetch;
    return stats;
}

std::size_t meshopt_target_index_count(std::size_t input_index_count, double ratio) {
    if (!std::isfinite(ratio) || ratio <= 0.0 || ratio >= 1.0 || input_index_count < 6) {
        return input_index_count;
    }
    const std::size_t input_triangles = input_index_count / 3;
    std::size_t target_triangles = static_cast<std::size_t>(std::floor(static_cast<double>(input_triangles) * ratio));
    target_triangles = std::max<std::size_t>(1, target_triangles);
    const std::size_t target_index_count = target_triangles * 3;
    return std::min(input_index_count, target_index_count);
}

std::vector<SubmeshOptimizeResult> run_optimize(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    double simplify_ratio = 1.0;
    double target_error = 0.01;
    const JsonValue* optimize = root.get("optimize");
    if (optimize != nullptr && optimize->type == JsonValue::Type::Object) {
        simplify_ratio = number_or(optimize->get("simplify_ratio"), simplify_ratio);
        target_error = number_or(optimize->get("target_error"), target_error);
    }
    if (!std::isfinite(simplify_ratio) || simplify_ratio <= 0.0) {
        simplify_ratio = 1.0;
    }
    simplify_ratio = std::min(1.0, simplify_ratio);
    if (!std::isfinite(target_error) || target_error < 0.0) {
        target_error = 0.01;
    }

    std::vector<SubmeshOptimizeResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty() || faces.empty()) {
            continue;
        }

        const std::vector<float> positions = meshopt_positions_from_vertices(vertices);
        std::vector<unsigned int> indices = meshopt_indices_from_faces(faces);
        SubmeshOptimizeResult result;
        result.index = index;
        result.input_vertex_count = static_cast<int>(vertices.size());
        result.input_index_count = static_cast<int>(indices.size());
        result.input_triangle_count = static_cast<int>(indices.size() / 3);
        result.target_ratio = simplify_ratio;
        result.target_error = target_error;
        result.before = meshopt_stats(indices, positions, vertices.size());

        std::vector<unsigned int> optimized(indices.size());
        meshopt_optimizeVertexCache(optimized.data(), indices.data(), indices.size(), vertices.size());
        if (!optimized.empty()) {
            std::vector<unsigned int> overdraw(optimized.size());
            meshopt_optimizeOverdraw(overdraw.data(), optimized.data(), optimized.size(), positions.data(), vertices.size(), sizeof(float) * 3, 1.05f);
            optimized = std::move(overdraw);
        }

        const std::size_t target_index_count = meshopt_target_index_count(indices.size(), simplify_ratio);
        if (target_index_count < optimized.size()) {
            std::vector<unsigned int> simplified(optimized.size());
            float result_error = 0.0f;
            const std::size_t simplified_count = meshopt_simplify(
                simplified.data(),
                optimized.data(),
                optimized.size(),
                positions.data(),
                vertices.size(),
                sizeof(float) * 3,
                target_index_count,
                static_cast<float>(target_error),
                0,
                &result_error
            );
            if (simplified_count >= 3 && simplified_count < optimized.size()) {
                simplified.resize(simplified_count - (simplified_count % 3));
                optimized = std::move(simplified);
                result.result_error = result_error;
                result.simplified = true;
                if (!optimized.empty()) {
                    std::vector<unsigned int> recached(optimized.size());
                    meshopt_optimizeVertexCache(recached.data(), optimized.data(), optimized.size(), vertices.size());
                    optimized = std::move(recached);
                }
            }
        }

        std::vector<unsigned int> fetch_remap(vertices.size());
        result.fetch_vertex_count = static_cast<int>(meshopt_optimizeVertexFetchRemap(fetch_remap.data(), optimized.data(), optimized.size(), vertices.size()));
        result.referenced_vertex_count = result.fetch_vertex_count;
        result.output_index_count = static_cast<int>(optimized.size());
        result.output_triangle_count = static_cast<int>(optimized.size() / 3);
        result.topology_changed = result.output_index_count != result.input_index_count;
        result.after = meshopt_stats(optimized, positions, vertices.size());
        result.faces = faces_from_meshopt_indices(optimized);
        results.push_back(std::move(result));
    }
    return results;
}

Vec2 rotate_uv(const Vec2& value, const Vec2& pivot, double degrees) {
    const double radians = degrees * 3.14159265358979323846 / 180.0;
    const double cos_v = std::cos(radians);
    const double sin_v = std::sin(radians);
    const double u = value[0] - pivot[0];
    const double v = value[1] - pivot[1];
    return {
        pivot[0] + (u * cos_v - v * sin_v),
        pivot[1] + (u * sin_v + v * cos_v),
    };
}

bool same_vec2(const Vec2& left, const Vec2& right) {
    return std::abs(left[0] - right[0]) <= 1e-8
        && std::abs(left[1] - right[1]) <= 1e-8;
}

Vec2 transform_uv(const Vec2& uv, const UvTransform& transform) {
    double u = uv[0];
    double v = uv[1];
    if (transform.flip_u) {
        u = (2.0 * transform.pivot[0]) - u;
    }
    if (transform.flip_v) {
        v = (2.0 * transform.pivot[1]) - v;
    }
    u = transform.pivot[0] + ((u - transform.pivot[0]) * transform.scale[0]);
    v = transform.pivot[1] + ((v - transform.pivot[1]) * transform.scale[1]);
    Vec2 result{u, v};
    if (std::abs(transform.rotate) > 1e-8) {
        result = rotate_uv(result, transform.pivot, transform.rotate);
    }
    return {result[0] + transform.offset[0], result[1] + transform.offset[1]};
}

bool uv_transform_projects(const UvTransform& transform) {
    return transform.projection == "planar"
        || transform.projection == "xy"
        || transform.projection == "xz"
        || transform.projection == "yz"
        || transform.projection == "box"
        || transform.projection == "cube"
        || transform.projection == "cylindrical"
        || transform.projection == "cylinder";
}

std::array<int, 2> uv_plane_axes(const std::string& plane) {
    const std::string normalized = lower_ascii(plane.empty() ? "xy" : plane);
    if (normalized == "xz") {
        return {0, 2};
    }
    if (normalized == "yz") {
        return {1, 2};
    }
    return {0, 1};
}

std::map<int, Vec2> project_points_to_uvs(const std::map<int, Vec3>& points, const std::array<int, 2>& axes) {
    std::map<int, Vec2> result;
    if (points.empty()) {
        return result;
    }
    double left_min = 1.0e300;
    double left_max = -1.0e300;
    double right_min = 1.0e300;
    double right_max = -1.0e300;
    for (const auto& item : points) {
        const Vec3& point = item.second;
        left_min = std::min(left_min, point[axes[0]]);
        left_max = std::max(left_max, point[axes[0]]);
        right_min = std::min(right_min, point[axes[1]]);
        right_max = std::max(right_max, point[axes[1]]);
    }
    const double left_span = left_max - left_min;
    const double right_span = right_max - right_min;
    for (const auto& item : points) {
        const Vec3& point = item.second;
        result[item.first] = {
            std::abs(left_span) <= 1e-12 ? 0.0 : (point[axes[0]] - left_min) / left_span,
            std::abs(right_span) <= 1e-12 ? 0.0 : (point[axes[1]] - right_min) / right_span,
        };
    }
    return result;
}

std::array<int, 2> box_projection_axes(const Vec3& normal) {
    const double x = std::abs(normal[0]);
    const double y = std::abs(normal[1]);
    const double z = std::abs(normal[2]);
    if (x >= y && x >= z) {
        return {1, 2};
    }
    if (y >= x && y >= z) {
        return {0, 2};
    }
    return {0, 1};
}

std::map<int, Vec2> projected_uvs(
    const std::vector<Vec3>& vertices,
    const std::vector<Vec3>& normals,
    const std::vector<int>& selected,
    const UvTransform& transform
) {
    std::map<int, Vec2> result;
    if (!uv_transform_projects(transform) || vertices.empty() || selected.empty()) {
        return result;
    }
    if (transform.projection == "cylindrical" || transform.projection == "cylinder") {
        std::array<int, 2> angle_axes{0, 1};
        int height_axis = 2;
        if (transform.axis == "x") {
            angle_axes = {1, 2};
            height_axis = 0;
        } else if (transform.axis == "y") {
            angle_axes = {0, 2};
            height_axis = 1;
        }
        double height_min = 1.0e300;
        double height_max = -1.0e300;
        for (const int index : selected) {
            if (index >= 0 && static_cast<std::size_t>(index) < vertices.size()) {
                height_min = std::min(height_min, vertices[static_cast<std::size_t>(index)][height_axis]);
                height_max = std::max(height_max, vertices[static_cast<std::size_t>(index)][height_axis]);
            }
        }
        const double height_span = height_max - height_min;
        for (const int index : selected) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
                continue;
            }
            const Vec3& point = vertices[static_cast<std::size_t>(index)];
            result[index] = {
                (std::atan2(point[angle_axes[1]], point[angle_axes[0]]) + 3.14159265358979323846)
                    / (2.0 * 3.14159265358979323846),
                std::abs(height_span) <= 1e-12 ? 0.0 : (point[height_axis] - height_min) / height_span,
            };
        }
        return result;
    }
    if (transform.projection == "box" || transform.projection == "cube") {
        std::map<std::array<int, 2>, std::map<int, Vec3>> points_by_axes;
        for (const int index : selected) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
                continue;
            }
            const Vec3 normal = static_cast<std::size_t>(index) < normals.size()
                ? normals[static_cast<std::size_t>(index)]
                : Vec3{0.0, 0.0, 1.0};
            points_by_axes[box_projection_axes(normal)][index] = vertices[static_cast<std::size_t>(index)];
        }
        for (const auto& item : points_by_axes) {
            const std::map<int, Vec2> projected = project_points_to_uvs(item.second, item.first);
            result.insert(projected.begin(), projected.end());
        }
        return result;
    }
    std::string plane = transform.plane;
    if (plane.empty() && (transform.projection == "xy" || transform.projection == "xz" || transform.projection == "yz")) {
        plane = transform.projection;
    }
    if (plane.empty()) {
        plane = "xy";
    }
    std::map<int, Vec3> points;
    for (const int index : selected) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertices.size()) {
            points[index] = vertices[static_cast<std::size_t>(index)];
        }
    }
    return project_points_to_uvs(points, uv_plane_axes(plane));
}

void normalize_uv_indices(std::vector<Vec2>& uvs, const std::vector<int>& selected, const Vec2& target_min, const Vec2& target_max) {
    if (selected.empty()) {
        return;
    }
    double min_u = 1.0e300;
    double max_u = -1.0e300;
    double min_v = 1.0e300;
    double max_v = -1.0e300;
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        const Vec2& uv = uvs[static_cast<std::size_t>(index)];
        min_u = std::min(min_u, uv[0]);
        max_u = std::max(max_u, uv[0]);
        min_v = std::min(min_v, uv[1]);
        max_v = std::max(max_v, uv[1]);
    }
    const double span_u = max_u - min_u;
    const double span_v = max_v - min_v;
    const double target_span_u = target_max[0] - target_min[0];
    const double target_span_v = target_max[1] - target_min[1];
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        Vec2& uv = uvs[static_cast<std::size_t>(index)];
        uv = {
            std::abs(span_u) <= 1e-12 ? target_min[0] : target_min[0] + ((uv[0] - min_u) / span_u) * target_span_u,
            std::abs(span_v) <= 1e-12 ? target_min[1] : target_min[1] + ((uv[1] - min_v) / span_v) * target_span_v,
        };
    }
}

long long rounded_uv_component(double value) {
    const long long rounded = static_cast<long long>(std::llround(value * 1000000.0));
    return rounded == 0 ? 0 : rounded;
}

using PackedUvEdgeKey = std::tuple<int, int, long long, long long, long long, long long>;

PackedUvEdgeKey packed_uv_edge_key(int left, int right, const std::vector<Vec2>& uvs) {
    const std::array<int, 2> vertex_edge = edge_key(left, right);
    std::pair<long long, long long> left_uv{
        rounded_uv_component(uvs[static_cast<std::size_t>(left)][0]),
        rounded_uv_component(uvs[static_cast<std::size_t>(left)][1]),
    };
    std::pair<long long, long long> right_uv{
        rounded_uv_component(uvs[static_cast<std::size_t>(right)][0]),
        rounded_uv_component(uvs[static_cast<std::size_t>(right)][1]),
    };
    if (right_uv < left_uv) {
        std::swap(left_uv, right_uv);
    }
    return {
        vertex_edge[0],
        vertex_edge[1],
        left_uv.first,
        left_uv.second,
        right_uv.first,
        right_uv.second,
    };
}

std::vector<std::set<int>> selected_uv_islands(
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<Vec2>& uvs,
    const std::vector<int>& selected
) {
    std::set<int> selected_set(selected.begin(), selected.end());
    if (selected_set.empty()) {
        return {};
    }
    std::map<PackedUvEdgeKey, std::set<int>> edge_faces;
    std::vector<std::vector<PackedUvEdgeKey>> face_edges;
    std::vector<std::array<int, 3>> face_vertices;
    std::set<int> seed_faces;
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const std::array<int, 3>& face = faces[face_index];
        face_vertices.push_back(face);
        if (selected_set.find(face[0]) != selected_set.end()
            || selected_set.find(face[1]) != selected_set.end()
            || selected_set.find(face[2]) != selected_set.end()) {
            seed_faces.insert(static_cast<int>(face_index));
        }
        std::vector<PackedUvEdgeKey> edges;
        for (int edge_index = 0; edge_index < 3; ++edge_index) {
            const int left = face[edge_index];
            const int right = face[(edge_index + 1) % 3];
            if (left < 0 || right < 0 || static_cast<std::size_t>(left) >= uvs.size() || static_cast<std::size_t>(right) >= uvs.size()) {
                continue;
            }
            edges.push_back(packed_uv_edge_key(left, right, uvs));
            edge_faces[edges.back()].insert(static_cast<int>(face_index));
        }
        face_edges.push_back(std::move(edges));
    }

    std::set<int> visited;
    std::vector<std::set<int>> islands;
    for (const int seed_face : seed_faces) {
        std::vector<int> pending{seed_face};
        std::set<int> island_faces;
        while (!pending.empty()) {
            const int face_index = pending.back();
            pending.pop_back();
            if (face_index < 0
                || static_cast<std::size_t>(face_index) >= face_edges.size()
                || visited.find(face_index) != visited.end()) {
                continue;
            }
            visited.insert(face_index);
            island_faces.insert(face_index);
            for (const PackedUvEdgeKey& edge : face_edges[static_cast<std::size_t>(face_index)]) {
                const auto found = edge_faces.find(edge);
                if (found == edge_faces.end()) {
                    continue;
                }
                for (const int connected_face : found->second) {
                    if (visited.find(connected_face) == visited.end()) {
                        pending.push_back(connected_face);
                    }
                }
            }
        }
        std::set<int> island_vertices;
        for (const int face_index : island_faces) {
            const std::array<int, 3>& face = face_vertices[static_cast<std::size_t>(face_index)];
            for (const int vertex_index : face) {
                island_vertices.insert(vertex_index);
            }
        }
        if (!island_vertices.empty()) {
            islands.push_back(std::move(island_vertices));
        }
    }
    std::set<int> packed_vertices;
    for (const std::set<int>& island : islands) {
        packed_vertices.insert(island.begin(), island.end());
    }
    for (const int index : selected_set) {
        if (packed_vertices.find(index) == packed_vertices.end()) {
            islands.push_back(std::set<int>{index});
        }
    }
    std::sort(islands.begin(), islands.end(), [](const std::set<int>& left, const std::set<int>& right) {
        return *left.begin() < *right.begin();
    });
    return islands;
}

void pack_uvs(
    std::vector<Vec2>& uvs,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<int>& selected,
    const UvTransform& transform
) {
    const std::vector<std::set<int>> islands = selected_uv_islands(faces, uvs, selected);
    if (islands.empty()) {
        return;
    }
    const int columns = transform.pack_columns > 0
        ? transform.pack_columns
        : std::max(1, static_cast<int>(std::ceil(std::sqrt(static_cast<double>(islands.size())))));
    const int rows = std::max(1, static_cast<int>(std::ceil(static_cast<double>(islands.size()) / static_cast<double>(columns))));
    const double cell_width = 1.0 / static_cast<double>(columns);
    const double cell_height = 1.0 / static_cast<double>(rows);
    const double inset_u = std::min(std::max(0.0, transform.pack_padding), cell_width * 0.45);
    const double inset_v = std::min(std::max(0.0, transform.pack_padding), cell_height * 0.45);
    for (std::size_t island_index = 0; island_index < islands.size(); ++island_index) {
        const int column = static_cast<int>(island_index) % columns;
        const int row = static_cast<int>(island_index) / columns;
        const Vec2 target_min{
            column * cell_width + inset_u,
            row * cell_height + inset_v,
        };
        const Vec2 target_max{
            (column + 1) * cell_width - inset_u,
            (row + 1) * cell_height - inset_v,
        };
        std::vector<int> island_vertices(islands[island_index].begin(), islands[island_index].end());
        normalize_uv_indices(uvs, island_vertices, target_min, target_max);
    }
}
