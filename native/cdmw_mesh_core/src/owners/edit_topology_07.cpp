bool build_tangent_split_result(
    const JsonValue& item,
    const std::vector<Vec3>& source_vertices,
    const std::vector<Vec2>& source_uvs,
    const std::vector<Vec3>& source_normals,
    const std::vector<std::array<int, 3>>& source_faces,
    const TangentBuildResult& build,
    SubmeshTangentsResult& result
) {
    if (result.vertices_path.empty()
        || result.faces_path.empty()
        || result.uvs_path.empty()
        || result.normals_path.empty()
        || result.tangents_path.empty()
        || result.tangent_signs_path.empty()) {
        return false;
    }
    if (source_vertices.empty()
        || source_uvs.size() != source_vertices.size()
        || source_normals.size() != source_vertices.size()
        || build.face_corner_tangents.size() != source_faces.size()) {
        return false;
    }

    BoneAssignments source_bones = mesh_bones_from_item(item);
    const bool has_bones = valid_bone_assignments(source_bones)
        && source_bones.indices.size() == source_vertices.size()
        && source_bones.weights.size() == source_vertices.size()
        && !result.bone_counts_path.empty()
        && !result.bone_indices_path.empty()
        && !result.bone_weights_path.empty();
    std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
        item,
        "source_vertex_map_binary",
        "source_vertex_map",
        "source_vertex_map_start",
        "source_vertex_map_count"
    );
    std::vector<int> source_vertex_offsets = source_vertex_offsets_from_item(item);
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (source_vertex_map.empty()) {
            source_vertex_map = session->source_vertex_map;
        }
        if (source_vertex_offsets.empty()) {
            source_vertex_offsets = session->source_vertex_offsets;
        }
    }
    const bool has_source_vertex_map = source_vertex_map.size() == source_vertices.size() && !result.source_vertex_map_path.empty();
    const bool has_source_vertex_offsets = source_vertex_offsets.size() == source_vertices.size() && !result.source_vertex_offsets_path.empty();

    std::map<std::tuple<int, double, double, double, double>, int> corner_index_by_key;
    std::vector<Vec3> split_vertices;
    std::vector<Vec2> split_uvs;
    std::vector<Vec3> split_normals;
    std::vector<Vec3> split_tangents;
    std::vector<double> split_tangent_signs;
    std::vector<std::array<int, 3>> split_faces;
    BoneAssignments split_bones;
    std::vector<int> split_source_vertex_map;
    std::vector<int> split_source_vertex_offsets;

    split_faces.reserve(source_faces.size());
    for (std::size_t face_index = 0; face_index < source_faces.size(); ++face_index) {
        const FaceCornerTangents& face_corners = build.face_corner_tangents[face_index];
        if (face_corners.face_index != static_cast<int>(face_index) || face_corners.vertices != source_faces[face_index]) {
            return false;
        }
        std::array<int, 3> split_face{0, 0, 0};
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const int old_index = face_corners.vertices[corner];
            if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
                return false;
            }
            const Vec3 tangent = face_corners.tangents[corner];
            const double sign = face_corners.signs[corner] >= 0.0 ? 1.0 : -1.0;
            const auto key = std::make_tuple(old_index, tangent[0], tangent[1], tangent[2], sign);
            auto existing = corner_index_by_key.find(key);
            int new_index = -1;
            if (existing != corner_index_by_key.end()) {
                new_index = existing->second;
            } else {
                if (split_vertices.size() >= static_cast<std::size_t>(INT_MAX)) {
                    return false;
                }
                new_index = static_cast<int>(split_vertices.size());
                corner_index_by_key[key] = new_index;
                const std::size_t source_index = static_cast<std::size_t>(old_index);
                split_vertices.push_back(source_vertices[source_index]);
                split_uvs.push_back(source_uvs[source_index]);
                split_normals.push_back(source_normals[source_index]);
                split_tangents.push_back(tangent);
                split_tangent_signs.push_back(sign);
                if (has_bones) {
                    split_bones.indices.push_back(source_bones.indices[source_index]);
                    split_bones.weights.push_back(source_bones.weights[source_index]);
                }
                if (has_source_vertex_map) {
                    split_source_vertex_map.push_back(source_vertex_map[source_index]);
                }
                if (has_source_vertex_offsets) {
                    split_source_vertex_offsets.push_back(source_vertex_offsets[source_index]);
                }
            }
            split_face[corner] = new_index;
        }
        split_faces.push_back(split_face);
    }

    result.vertices = std::move(split_vertices);
    result.faces = std::move(split_faces);
    result.uvs = std::move(split_uvs);
    result.normals = std::move(split_normals);
    result.tangents = std::move(split_tangents);
    result.tangent_signs = std::move(split_tangent_signs);
    result.bones = std::move(split_bones);
    result.source_vertex_map = std::move(split_source_vertex_map);
    result.source_vertex_offsets = std::move(split_source_vertex_offsets);
    result.topology_split_applied = result.vertices.size() == result.tangents.size()
        && result.vertices.size() == result.tangent_signs.size()
        && result.vertices.size() == result.uvs.size()
        && result.vertices.size() == result.normals.size();
    return result.topology_split_applied;
}

std::vector<SubmeshTangentsResult> run_generate_tangents(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshTangentsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        std::vector<Vec3> normals = mesh_normals_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty() || uvs.size() != vertices.size() || faces.empty()) {
            continue;
        }
        if (normals.size() != vertices.size()) {
            normals = compute_smooth_normals(vertices, faces);
        }
        SubmeshTangentsResult result;
        result.index = index;
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.tangents_path = string_or(item.get("tangents_output_path"), "");
        result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        TangentBuildResult build = compute_tangent_basis(
            vertices,
            uvs,
            normals,
            faces
        );
        result.tangent_backend = build.tangent_backend;
        result.tangents = build.vertex_tangents;
        result.tangent_signs = build.vertex_signs;
        const std::vector<Vec3> existing_tangents = mesh_tangents_from_item(item);
        if (existing_tangents.size() == result.tangents.size()) {
            for (std::size_t tangent_index = 0; tangent_index < result.tangents.size(); ++tangent_index) {
                if (!same_vec3(existing_tangents[tangent_index], result.tangents[tangent_index])) {
                    result.changed_vertices.push_back(static_cast<int>(tangent_index));
                }
            }
        } else {
            result.changed_vertices.reserve(result.tangents.size());
            for (std::size_t tangent_index = 0; tangent_index < result.tangents.size(); ++tangent_index) {
                result.changed_vertices.push_back(static_cast<int>(tangent_index));
            }
        }
        result.split_required_vertices = std::move(build.split_required_vertices);
        result.face_corner_tangent_count = build.face_corner_tangent_count;
        result.degenerate_uv_faces = build.degenerate_uv_faces;
        result.vertex_storage_safe = build.vertex_storage_safe;
        if (!build.vertex_storage_safe) {
            build_tangent_split_result(item, vertices, uvs, normals, faces, build, result);
        }
        if (!result.topology_split_applied) {
            result.face_corner_tangents = std::move(build.face_corner_tangents);
        }
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            if (result.topology_split_applied) {
                session->vertices = result.vertices;
                session->faces = result.faces;
                session->normals = result.normals;
                session->uvs = result.uvs;
                session->tangents = result.tangents;
                session->tangent_signs = result.tangent_signs;
                if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
                    session->bone_indices = result.bones.indices;
                    session->bone_weights = result.bones.weights;
                }
                if (result.source_vertex_map.size() == result.vertices.size()) {
                    session->source_vertex_map = result.source_vertex_map;
                }
                if (result.source_vertex_offsets.size() == result.vertices.size()) {
                    session->source_vertex_offsets = result.source_vertex_offsets;
                }
            } else if (session->vertices.size() == result.tangents.size()) {
                session->tangents = result.tangents;
                session->tangent_signs = result.tangent_signs;
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<Vec3> morph_delta_for_submesh(const JsonValue& delta_item, int submesh_index) {
    const JsonValue* delta_submeshes = delta_item.get("submeshes");
    if (delta_submeshes == nullptr || delta_submeshes->type != JsonValue::Type::Array) {
        return {};
    }
    for (const JsonValue& item : delta_submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        if (int_or(item.get("index"), -1) == submesh_index) {
            return vertices_from_binary_or_json(item, "deltas_binary", "deltas");
        }
    }
    return {};
}

std::map<int, double> region_volume_selection_weights(
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces,
    const std::set<int>& selected,
    int feather
) {
    std::map<int, double> weights;
    for (const int index : selected) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            weights[index] = 1.0;
        }
    }
    const int rings = std::max(0, feather);
    if (weights.empty() || rings <= 0) {
        return weights;
    }
    const std::vector<std::set<int>> adjacency = build_vertex_adjacency(vertex_count, faces);
    std::set<int> frontier;
    std::set<int> visited;
    for (const auto& item : weights) {
        frontier.insert(item.first);
        visited.insert(item.first);
    }
    for (int depth = 1; depth <= rings; ++depth) {
        std::set<int> next_frontier;
        for (const int index : frontier) {
            if (index < 0 || static_cast<std::size_t>(index) >= adjacency.size()) {
                continue;
            }
            for (const int neighbor : adjacency[static_cast<std::size_t>(index)]) {
                if (visited.find(neighbor) == visited.end()) {
                    next_frontier.insert(neighbor);
                }
            }
        }
        if (next_frontier.empty()) {
            break;
        }
        const double weight = std::max(0.0, 1.0 - (static_cast<double>(depth) / static_cast<double>(rings + 1)));
        for (const int index : next_frontier) {
            auto found = weights.find(index);
            if (found == weights.end() || found->second < weight) {
                weights[index] = weight;
            }
            visited.insert(index);
        }
        frontier = std::move(next_frontier);
    }
    return weights;
}

std::vector<SubmeshRegionVolumeDeltaResult> run_region_volume_delta(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const double amount = number_or(root.get("amount"), 0.0);
    const int feather = std::max(0, int_or(root.get("feather"), 0));
    std::vector<SubmeshRegionVolumeDeltaResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty()) {
            continue;
        }
        std::set<int> selected = selected_vertices_from_binary_or_json(item, vertices.size());
        std::map<int, double> weights = region_volume_selection_weights(vertices.size(), faces, selected, feather);
        Vec3 center{0.0, 0.0, 0.0};
        for (const auto& entry : weights) {
            const Vec3& vertex = vertices[static_cast<std::size_t>(entry.first)];
            center[0] += vertex[0];
            center[1] += vertex[1];
            center[2] += vertex[2];
        }
        if (!weights.empty()) {
            const double denominator = static_cast<double>(weights.size());
            center = {center[0] / denominator, center[1] / denominator, center[2] / denominator};
        }
        const std::vector<Vec3> normals = compute_smooth_normals(vertices, faces);
        SubmeshRegionVolumeDeltaResult result;
        result.index = index;
        result.deltas_path = string_or(item.get("deltas_output_path"), "");
        result.vertex_count = static_cast<int>(vertices.size());
        result.selected_vertex_count = static_cast<int>(selected.size());
        result.weighted_vertex_count = static_cast<int>(weights.size());
        result.deltas.reserve(vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
            double weight = 0.0;
            const auto found = weights.find(static_cast<int>(vertex_index));
            if (found != weights.end()) {
                weight = std::max(0.0, std::min(1.0, found->second));
            }
            if (weight <= 0.0) {
                result.deltas.push_back({0.0, 0.0, 0.0});
                continue;
            }
            const Vec3 radial = normalized_vec3(sub_vec3(vertices[vertex_index], center), {0.0, 1.0, 0.0});
            const Vec3 normal = vertex_index < normals.size() ? normalized_vec3(normals[vertex_index], radial) : radial;
            result.deltas.push_back(scale_vec3(normal, amount * weight));
        }
        write_vec3_binary_file(result.deltas_path, result.deltas);
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshMorphApplyResult> run_morph_apply(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const JsonValue* deltas = root.get("deltas");
    std::vector<SubmeshMorphApplyResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (deltas != nullptr && deltas->type == JsonValue::Type::Array) {
            for (const JsonValue& delta_item : deltas->array_value) {
                if (delta_item.type != JsonValue::Type::Object) {
                    continue;
                }
                const double factor = number_or(delta_item.get("factor"), 0.0);
                if (std::abs(factor) <= 1e-15) {
                    continue;
                }
                const std::vector<Vec3> delta_vertices = morph_delta_for_submesh(delta_item, index);
                const std::size_t count = std::min(vertices.size(), delta_vertices.size());
                for (std::size_t vertex_index = 0; vertex_index < count; ++vertex_index) {
                    vertices[vertex_index][0] += delta_vertices[vertex_index][0] * factor;
                    vertices[vertex_index][1] += delta_vertices[vertex_index][1] * factor;
                    vertices[vertex_index][2] += delta_vertices[vertex_index][2] * factor;
                }
            }
        }
        const std::vector<Vec3> post_edit_deltas = vertices_from_binary_or_json(item, "post_edit_deltas_binary", "post_edit_deltas");
        const std::size_t post_count = std::min(vertices.size(), post_edit_deltas.size());
        for (std::size_t vertex_index = 0; vertex_index < post_count; ++vertex_index) {
            vertices[vertex_index][0] += post_edit_deltas[vertex_index][0];
            vertices[vertex_index][1] += post_edit_deltas[vertex_index][1];
            vertices[vertex_index][2] += post_edit_deltas[vertex_index][2];
        }
        for (const Vec3& vertex : vertices) {
            if (!std::isfinite(vertex[0]) || !std::isfinite(vertex[1]) || !std::isfinite(vertex[2])) {
                throw std::runtime_error("non-finite morph output vertex");
            }
        }
        const std::vector<Vec3> normals = compute_smooth_normals(vertices, faces);
        const std::string vertices_path = string_or(item.get("output_vertices_path"), "");
        const std::string normals_path = string_or(item.get("output_normals_path"), "");
        write_vec3_binary_file(vertices_path, vertices);
        write_vec3_binary_file(normals_path, normals);

        SubmeshMorphApplyResult result;
        result.index = index;
        result.vertices_path = vertices_path;
        result.normals_path = normals_path;
        result.vertex_count = static_cast<int>(vertices.size());
        result.normal_count = static_cast<int>(normals.size());
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshMorphPostEditDeltaResult> run_morph_post_edit_delta(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshMorphPostEditDeltaResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        const std::vector<Vec3> working_vertices =
            vertices_from_binary_or_json(item, "working_vertices_binary", "working_vertices");
        const std::vector<Vec3> slider_vertices =
            vertices_from_binary_or_json(item, "slider_vertices_binary", "slider_vertices");
        if (working_vertices.size() != slider_vertices.size()) {
            throw std::runtime_error("morph post-edit vertex count mismatch");
        }
        SubmeshMorphPostEditDeltaResult result;
        result.index = index;
        result.deltas_path = string_or(item.get("deltas_output_path"), "");
        result.vertex_count = static_cast<int>(working_vertices.size());
        result.zero_delta = true;
        result.deltas.reserve(working_vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < working_vertices.size(); ++vertex_index) {
            Vec3 delta{
                working_vertices[vertex_index][0] - slider_vertices[vertex_index][0],
                working_vertices[vertex_index][1] - slider_vertices[vertex_index][1],
                working_vertices[vertex_index][2] - slider_vertices[vertex_index][2],
            };
            if (!std::isfinite(delta[0]) || !std::isfinite(delta[1]) || !std::isfinite(delta[2])) {
                throw std::runtime_error("non-finite morph post-edit delta");
            }
            if (delta[0] != 0.0 || delta[1] != 0.0 || delta[2] != 0.0) {
                result.zero_delta = false;
            }
            result.deltas.push_back(delta);
        }
        if (!result.zero_delta) {
            write_vec3_binary_file(result.deltas_path, result.deltas);
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshMorphPostEditDeltaResult> run_morph_target_delta(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshMorphPostEditDeltaResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        const std::vector<Vec3> base_vertices =
            vertices_from_binary_or_json(item, "base_vertices_binary", "base_vertices");
        const std::vector<Vec3> target_vertices =
            vertices_from_binary_or_json(item, "target_vertices_binary", "target_vertices");
        if (base_vertices.size() != target_vertices.size()) {
            throw std::runtime_error("morph target vertex count mismatch");
        }
        const std::vector<std::array<int, 3>> base_faces =
            faces_from_binary_or_json_keys(item, "base_faces_binary", "base_faces", base_vertices.size());
        const std::vector<std::array<int, 3>> target_faces =
            faces_from_binary_or_json_keys(item, "target_faces_binary", "target_faces", target_vertices.size());
        if (base_faces.size() != target_faces.size()) {
            throw std::runtime_error("morph target face count mismatch");
        }
        if (base_faces != target_faces) {
            throw std::runtime_error("morph target face topology mismatch");
        }
        SubmeshMorphPostEditDeltaResult result;
        result.index = index;
        result.deltas_path = string_or(item.get("deltas_output_path"), "");
        result.vertex_count = static_cast<int>(base_vertices.size());
        result.deltas.reserve(base_vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < base_vertices.size(); ++vertex_index) {
            Vec3 delta{
                target_vertices[vertex_index][0] - base_vertices[vertex_index][0],
                target_vertices[vertex_index][1] - base_vertices[vertex_index][1],
                target_vertices[vertex_index][2] - base_vertices[vertex_index][2],
            };
            if (!std::isfinite(delta[0]) || !std::isfinite(delta[1]) || !std::isfinite(delta[2])) {
                throw std::runtime_error("non-finite morph target delta");
            }
            result.deltas.push_back(delta);
        }
        write_vec3_binary_file(result.deltas_path, result.deltas);
        results.push_back(std::move(result));
    }
    return results;
}

std::pair<Vec3, Vec3> static_donor_bbox(const std::vector<Vec3>& vertices) {
    if (vertices.empty()) {
        return {Vec3{0.0, 0.0, 0.0}, Vec3{1.0, 1.0, 1.0}};
    }
    Vec3 bbox_min = vertices.front();
    Vec3 bbox_max = vertices.front();
    for (const Vec3& vertex : vertices) {
        bbox_min[0] = std::min(bbox_min[0], vertex[0]);
        bbox_min[1] = std::min(bbox_min[1], vertex[1]);
        bbox_min[2] = std::min(bbox_min[2], vertex[2]);
        bbox_max[0] = std::max(bbox_max[0], vertex[0]);
        bbox_max[1] = std::max(bbox_max[1], vertex[1]);
        bbox_max[2] = std::max(bbox_max[2], vertex[2]);
    }
    constexpr double eps = 1.0e-6;
    bbox_min[0] -= eps;
    bbox_min[1] -= eps;
    bbox_min[2] -= eps;
    bbox_max[0] += eps;
    bbox_max[1] += eps;
    bbox_max[2] += eps;
    return {bbox_min, bbox_max};
}

double static_alignment_match_cost(
    const Vec3& orig_vertex,
    const Vec3& new_vertex,
    int orig_index,
    int new_index,
    double diag,
    int max_count
) {
    double dist = std::sqrt(distance_squared_vec3(orig_vertex, new_vertex));
    if (orig_index == new_index) {
        dist *= 0.75;
    } else if (std::abs(orig_index - new_index) <= 2) {
        dist *= 0.85;
    }
    const double order_penalty =
        (static_cast<double>(std::abs(orig_index - new_index)) / static_cast<double>(std::max(max_count, 1)))
        * std::max(diag * 0.05, 0.01);
    return dist + order_penalty;
}

std::vector<int> align_static_donor_vertex_sequences(
    const std::vector<Vec3>& orig_vertices,
    const std::vector<Vec3>& new_vertices
) {
    const int orig_count = static_cast<int>(orig_vertices.size());
    const int new_count = static_cast<int>(new_vertices.size());
    std::vector<int> aligned(static_cast<std::size_t>(new_count), -1);
    if (orig_count == 0 || new_count == 0) {
        return aligned;
    }

    const auto bbox = static_donor_bbox(orig_vertices);
    const double diag = std::sqrt(distance_squared_vec3(bbox.first, bbox.second));
    const double gap_penalty = std::max(diag * 0.02, 0.01);
    const int band = std::max(128, std::abs(orig_count - new_count) + 128);
    const long long max_states =
        static_cast<long long>(orig_count + 1) * static_cast<long long>(std::min(new_count + 1, band * 2 + 1));
    if (max_states > 3000000LL) {
        throw std::runtime_error("Static vertex alignment too large");
    }

    std::map<int, double> prev_row;
    const int first_row_end = std::min(new_count, band);
    for (int j = 0; j <= first_row_end; ++j) {
        prev_row[j] = static_cast<double>(j) * gap_penalty;
    }
    std::map<std::pair<int, int>, char> backtrack;
    for (int j = 1; j <= first_row_end; ++j) {
        backtrack[{0, j}] = 'l';
    }

    const int max_count = std::max(orig_count, new_count);
    for (int i = 1; i <= orig_count; ++i) {
        const int j_start = std::max(0, i - band);
        const int j_end = std::min(new_count, i + band);
        std::map<int, double> curr_row;
        if (j_start == 0) {
            curr_row[0] = static_cast<double>(i) * gap_penalty;
            backtrack[{i, 0}] = 'u';
        }

        for (int j = std::max(1, j_start); j <= j_end; ++j) {
            double best_cost = 1.0e300;
            char best_move = '\0';

            const auto diag_prev = prev_row.find(j - 1);
            if (diag_prev != prev_row.end()) {
                const double cost = diag_prev->second + static_alignment_match_cost(
                    orig_vertices[static_cast<std::size_t>(i - 1)],
                    new_vertices[static_cast<std::size_t>(j - 1)],
                    i - 1,
                    j - 1,
                    diag,
                    max_count
                );
                if (cost < best_cost) {
                    best_cost = cost;
                    best_move = 'd';
                }
            }

            const auto up_prev = prev_row.find(j);
            if (up_prev != prev_row.end()) {
                const double cost = up_prev->second + gap_penalty;
                if (cost < best_cost) {
                    best_cost = cost;
                    best_move = 'u';
                }
            }

            const auto left_prev = curr_row.find(j - 1);
            if (left_prev != curr_row.end()) {
                const double cost = left_prev->second + gap_penalty;
                if (cost < best_cost) {
                    best_cost = cost;
                    best_move = 'l';
                }
            }

            if (best_move != '\0') {
                curr_row[j] = best_cost;
                backtrack[{i, j}] = best_move;
            }
        }
        prev_row = std::move(curr_row);
    }

    if (prev_row.find(new_count) == prev_row.end()) {
        throw std::runtime_error("Static vertex alignment band did not reach the final state");
    }

    int i = orig_count;
    int j = new_count;
    while (i > 0 || j > 0) {
        const auto found = backtrack.find({i, j});
        const char move = found == backtrack.end() ? '\0' : found->second;
        if (move == 'd') {
            aligned[static_cast<std::size_t>(j - 1)] = i - 1;
            --i;
            --j;
        } else if (move == 'l') {
            --j;
        } else if (move == 'u') {
            --i;
        } else {
            if (j > 0 && i > 0) {
                aligned[static_cast<std::size_t>(j - 1)] = i - 1;
                --i;
                --j;
            } else if (j > 0) {
                --j;
            } else {
                --i;
            }
        }
    }
    return aligned;
}

long long static_donor_round_key(double value) {
    return static_cast<long long>(std::nearbyint(value * 100000.0));
}

std::tuple<long long, long long, long long> static_donor_rounded_key(const Vec3& vertex) {
    return {
        static_donor_round_key(vertex[0]),
        static_donor_round_key(vertex[1]),
        static_donor_round_key(vertex[2])
    };
}

std::tuple<int, int, int> static_donor_cell_key(const Vec3& vertex, double cell_size) {
    return {
        static_cast<int>(std::floor(vertex[0] / cell_size)),
        static_cast<int>(std::floor(vertex[1] / cell_size)),
        static_cast<int>(std::floor(vertex[2] / cell_size))
    };
}

std::pair<double, std::map<std::tuple<int, int, int>, std::vector<int>>> build_static_donor_spatial_hash(
    const std::vector<Vec3>& points
) {
    if (points.empty()) {
        return {1.0, {}};
    }
    Vec3 bbox_min = points.front();
    Vec3 bbox_max = points.front();
    for (const Vec3& point : points) {
        bbox_min[0] = std::min(bbox_min[0], point[0]);
        bbox_min[1] = std::min(bbox_min[1], point[1]);
        bbox_min[2] = std::min(bbox_min[2], point[2]);
        bbox_max[0] = std::max(bbox_max[0], point[0]);
        bbox_max[1] = std::max(bbox_max[1], point[1]);
        bbox_max[2] = std::max(bbox_max[2], point[2]);
    }
    const double extent = std::max(
        std::max(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1]),
        std::max(bbox_max[2] - bbox_min[2], 1.0e-5)
    );
    const int divisions = std::max(static_cast<int>(std::nearbyint(std::pow(static_cast<double>(points.size()), 1.0 / 3.0))), 1);
    const double cell_size = std::max(extent / static_cast<double>(divisions), 1.0e-5);
    std::map<std::tuple<int, int, int>, std::vector<int>> grid;
    for (std::size_t index = 0; index < points.size(); ++index) {
        grid[static_donor_cell_key(points[index], cell_size)].push_back(static_cast<int>(index));
    }
    return {cell_size, std::move(grid)};
}

int nearest_static_donor_point_index(
    const Vec3& point,
    const std::vector<Vec3>& source_points,
    double cell_size,
    const std::map<std::tuple<int, int, int>, std::vector<int>>& grid
) {
    if (source_points.empty()) {
        throw std::runtime_error("Cannot transfer displacement from an empty source mesh.");
    }
    const auto base = static_donor_cell_key(point, cell_size);
    const int base_x = std::get<0>(base);
    const int base_y = std::get<1>(base);
    const int base_z = std::get<2>(base);
    int best_index = -1;
    double best_d2 = 1.0e300;

    for (int radius = 0; radius < 8; ++radius) {
        bool found_any = false;
        for (int dx = -radius; dx <= radius; ++dx) {
            for (int dy = -radius; dy <= radius; ++dy) {
                for (int dz = -radius; dz <= radius; ++dz) {
                    const auto found = grid.find({base_x + dx, base_y + dy, base_z + dz});
                    if (found == grid.end()) {
                        continue;
                    }
                    for (const int index : found->second) {
                        found_any = true;
                        const double d2 = distance_squared_vec3(source_points[static_cast<std::size_t>(index)], point);
                        if (d2 < best_d2) {
                            best_d2 = d2;
                            best_index = index;
                        }
                    }
                }
            }
        }
        if (found_any && best_index >= 0) {
            return best_index;
        }
    }

    for (std::size_t index = 0; index < source_points.size(); ++index) {
        const double d2 = distance_squared_vec3(source_points[index], point);
        if (d2 < best_d2) {
            best_d2 = d2;
            best_index = static_cast<int>(index);
        }
    }
    return best_index;
}
