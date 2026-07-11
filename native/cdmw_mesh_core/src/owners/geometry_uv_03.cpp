bool uv_align_value(
    bool has_value,
    bool is_number,
    double number,
    const std::string& mode,
    const std::vector<double>& values,
    double& out
) {
    if (!has_value || values.empty()) {
        return false;
    }
    if (is_number) {
        out = number;
        return std::isfinite(out);
    }
    const auto minmax = std::minmax_element(values.begin(), values.end());
    if (mode == "min" || mode == "left" || mode == "bottom") {
        out = *minmax.first;
        return true;
    }
    if (mode == "max" || mode == "right" || mode == "top") {
        out = *minmax.second;
        return true;
    }
    if (mode == "center" || mode == "middle") {
        out = (*minmax.first + *minmax.second) / 2.0;
        return true;
    }
    char* end = nullptr;
    errno = 0;
    const double parsed = std::strtod(mode.c_str(), &end);
    if (end != mode.c_str() && end != nullptr && *end == '\0' && errno != ERANGE && std::isfinite(parsed)) {
        out = parsed;
        return true;
    }
    return false;
}

void align_uvs(std::vector<Vec2>& uvs, const std::vector<int>& selected, const UvTransform& transform) {
    std::vector<double> u_values;
    std::vector<double> v_values;
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        const Vec2& uv = uvs[static_cast<std::size_t>(index)];
        u_values.push_back(uv[0]);
        v_values.push_back(uv[1]);
    }
    double align_u = 0.0;
    double align_v = 0.0;
    const bool has_u = uv_align_value(transform.has_align_u, transform.align_u_is_number, transform.align_u_number, transform.align_u_mode, u_values, align_u);
    const bool has_v = uv_align_value(transform.has_align_v, transform.align_v_is_number, transform.align_v_number, transform.align_v_mode, v_values, align_v);
    if (!has_u && !has_v) {
        return;
    }
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        Vec2& uv = uvs[static_cast<std::size_t>(index)];
        if (has_u) {
            uv[0] = align_u;
        }
        if (has_v) {
            uv[1] = align_v;
        }
    }
}

void snap_uvs(std::vector<Vec2>& uvs, const std::vector<int>& selected, const UvTransform& transform) {
    if (!transform.snap || transform.snap_step[0] <= 0.0 || transform.snap_step[1] <= 0.0) {
        return;
    }
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        Vec2& uv = uvs[static_cast<std::size_t>(index)];
        uv[0] = snap_value(uv[0], transform.snap_step[0]);
        uv[1] = snap_value(uv[1], transform.snap_step[1]);
    }
}

std::vector<SubmeshUvTransformResult> run_uv_transform(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const UvTransform root_transform = uv_transform_from_json(root);
    std::vector<SubmeshUvTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const UvTransform transform = item.get("uv_transform") != nullptr ? uv_transform_from_json(item) : root_transform;
        SubmeshUvTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.uvs = mesh_uvs_from_item(item);
        result.vertices = mesh_vertices_from_item(item);
        result.normals = mesh_normals_from_item(item);
        const int vertex_count = static_cast<int>(mesh_vertex_count_from_item(item));
        const bool projects = uv_transform_projects(transform);
        const bool initialized_uvs = (transform.initialize_missing_uvs || projects)
            && vertex_count >= 0
            && static_cast<std::size_t>(vertex_count) != result.uvs.size();
        if (initialized_uvs) {
            result.uvs.assign(static_cast<std::size_t>(vertex_count), {0.0, 0.0});
        }
        if (result.index < 0 || result.uvs.empty() || vertex_count < 0 || static_cast<std::size_t>(vertex_count) != result.uvs.size()) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, result.uvs.size());
        const std::set<int> selected = selected_vertices_from_edit_domains(item, result.uvs.size(), faces);
        if (selected.empty()) {
            continue;
        }
        std::vector<int> selected_ordered;
        selected_ordered.reserve(selected.size());
        for (const int vertex_index : selected) {
            if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < result.uvs.size()) {
                selected_ordered.push_back(vertex_index);
            }
        }
        if (selected_ordered.empty()) {
            continue;
        }
        const std::vector<Vec2> original_uvs = result.uvs;
        if (transform.uv_island) {
            std::set<int> island_vertices;
            for (const std::set<int>& island : selected_uv_islands(faces, result.uvs, selected_ordered)) {
                island_vertices.insert(island.begin(), island.end());
            }
            selected_ordered.assign(island_vertices.begin(), island_vertices.end());
            if (selected_ordered.empty()) {
                continue;
            }
        }
        const std::vector<Vec3> vertices = (projects || transform.pack) ? mesh_vertices_from_item(item) : std::vector<Vec3>();
        const std::vector<Vec3> normals = projects ? mesh_normals_from_item(item) : std::vector<Vec3>();
        if ((projects || transform.pack) && !vertices.empty() && vertices.size() != result.uvs.size()) {
            continue;
        }
        if (projects && vertices.empty()) {
            continue;
        }
        const std::map<int, Vec2> projected = projected_uvs(vertices, normals, selected_ordered, transform);
        for (const int vertex_index : selected_ordered) {
            const Vec2 old_uv = result.uvs[static_cast<std::size_t>(vertex_index)];
            if (transform.validate_input_bounds
                && (old_uv[0] < transform.input_bounds_min[0]
                    || old_uv[0] > transform.input_bounds_max[0]
                    || old_uv[1] < transform.input_bounds_min[1]
                    || old_uv[1] > transform.input_bounds_max[1])) {
                result.status = "uv_out_of_bounds";
                result.error = "input UV outside allowed bounds";
                result.invalid_vertex_index = vertex_index;
                result.invalid_uv = old_uv;
                result.changed_vertices.clear();
                break;
            }
            Vec2 input_uv = old_uv;
            const auto projected_found = projected.find(vertex_index);
            if (projected_found != projected.end()) {
                input_uv = projected_found->second;
            }
            if (transform.clamp_input_uv) {
                input_uv[0] = std::max(transform.input_clamp_min[0], std::min(transform.input_clamp_max[0], input_uv[0]));
                input_uv[1] = std::max(transform.input_clamp_min[1], std::min(transform.input_clamp_max[1], input_uv[1]));
            }
            const Vec2 new_uv = transform_uv(input_uv, transform);
            result.uvs[static_cast<std::size_t>(vertex_index)] = new_uv;
        }
        if (result.status != "ok") {
            results.push_back(std::move(result));
            continue;
        }
        if (transform.normalize) {
            normalize_uv_indices(result.uvs, selected_ordered, transform.target_min, transform.target_max);
        }
        if (transform.pack) {
            pack_uvs(result.uvs, faces, selected_ordered, transform);
        }
        align_uvs(result.uvs, selected_ordered, transform);
        snap_uvs(result.uvs, selected_ordered, transform);
        for (const int vertex_index : selected_ordered) {
            if (initialized_uvs
                || !same_vec2(
                    original_uvs[static_cast<std::size_t>(vertex_index)],
                    result.uvs[static_cast<std::size_t>(vertex_index)]
                )) {
                result.changed_vertices.push_back(vertex_index);
            }
        }
        if (result.status == "ok" && !result.changed_vertices.empty()) {
            if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
                if (session->vertices.size() == result.uvs.size()) {
                    session->uvs = result.uvs;
                }
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

Vec3 face_normal(const Vec3& v0, const Vec3& v1, const Vec3& v2) {
    const double ax = v1[0] - v0[0];
    const double ay = v1[1] - v0[1];
    const double az = v1[2] - v0[2];
    const double bx = v2[0] - v0[0];
    const double by = v2[1] - v0[1];
    const double bz = v2[2] - v0[2];
    const double nx = ay * bz - az * by;
    const double ny = az * bx - ax * bz;
    const double nz = ax * by - ay * bx;
    const double length = std::sqrt(nx * nx + ny * ny + nz * nz);
    if (length > 1e-8) {
        return {nx / length, ny / length, nz / length};
    }
    return {0.0, 1.0, 0.0};
}

Vec3 normalized_vec3_or_zero(const Vec3& value) {
    const double length = std::sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
    if (length > 1e-12 && std::isfinite(length)) {
        return {value[0] / length, value[1] / length, value[2] / length};
    }
    return {0.0, 0.0, 0.0};
}

Vec3 face_cross(const Vec3& v0, const Vec3& v1, const Vec3& v2) {
    const double ax = v1[0] - v0[0];
    const double ay = v1[1] - v0[1];
    const double az = v1[2] - v0[2];
    const double bx = v2[0] - v0[0];
    const double by = v2[1] - v0[1];
    const double bz = v2[2] - v0[2];
    return {ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx};
}

std::vector<Vec3> compute_smooth_normals(const std::vector<Vec3>& vertices, const std::vector<std::array<int, 3>>& faces) {
    std::vector<Vec3> normals(vertices.size(), {0.0, 0.0, 0.0});
    for (const auto& face : faces) {
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const Vec3 normal = face_normal(vertices[static_cast<std::size_t>(a)], vertices[static_cast<std::size_t>(b)], vertices[static_cast<std::size_t>(c)]);
        for (const int index : face) {
            Vec3& target = normals[static_cast<std::size_t>(index)];
            target[0] += normal[0];
            target[1] += normal[1];
            target[2] += normal[2];
        }
    }
    for (Vec3& normal : normals) {
        const double length = std::sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
        if (length > 1e-8) {
            normal = {normal[0] / length, normal[1] / length, normal[2] / length};
        } else {
            normal = {0.0, 1.0, 0.0};
        }
    }
    return normals;
}

std::vector<Vec3> compute_weighted_normals(
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<Vec3>& fallback_normals
) {
    auto normalized_or = [](const Vec3& value, const Vec3& fallback) -> Vec3 {
        const double length = std::sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
        if (length > 1e-12 && std::isfinite(length)) {
            return {value[0] / length, value[1] / length, value[2] / length};
        }
        return fallback;
    };
    std::vector<Vec3> accum(vertices.size(), {0.0, 0.0, 0.0});
    for (const auto& face : faces) {
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const Vec3 weighted = face_cross(
            vertices[static_cast<std::size_t>(a)],
            vertices[static_cast<std::size_t>(b)],
            vertices[static_cast<std::size_t>(c)]
        );
        const double length_squared = weighted[0] * weighted[0] + weighted[1] * weighted[1] + weighted[2] * weighted[2];
        if (length_squared <= 1e-24 || !std::isfinite(length_squared)) {
            continue;
        }
        for (const int index : face) {
            Vec3& target = accum[static_cast<std::size_t>(index)];
            target[0] += weighted[0];
            target[1] += weighted[1];
            target[2] += weighted[2];
        }
    }
    std::vector<Vec3> result;
    result.reserve(vertices.size());
    for (std::size_t index = 0; index < accum.size(); ++index) {
        Vec3 normal = normalized_or(accum[index], {0.0, 0.0, 0.0});
        if (normal == Vec3{0.0, 0.0, 0.0} && index < fallback_normals.size()) {
            normal = normalized_or(fallback_normals[index], {0.0, 0.0, 0.0});
        }
        result.push_back(normal == Vec3{0.0, 0.0, 0.0} ? Vec3{0.0, 1.0, 0.0} : normal);
    }
    return result;
}

std::vector<SubmeshNormalsResult> run_recalculate_normals(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string operation = string_or(root.get("operation"), "recalculate_normals");
    std::vector<SubmeshNormalsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty() || (faces.empty() && operation != "copy_normals")) {
            continue;
        }
        SubmeshNormalsResult result;
        result.index = index;
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.preview_vertex_path = string_or(item.get("preview_vertex_output_path"), "");
        result.vertices = vertices;
        result.uvs = mesh_uvs_from_item(item);
        result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());
        const std::vector<Vec3> existing_normals = mesh_normals_from_item(item);
        if (operation == "weighted_normals") {
            result.normals = compute_weighted_normals(vertices, faces, existing_normals);
        } else if (operation == "copy_normals") {
            const std::vector<Vec3> source_normals = vertices_from_binary_or_json(item, "source_normals_binary", "source_normals");
            const std::set<int> selected_vertices = selected_vertices_from_edit_domains(item, vertices.size(), faces);
            if (source_normals.empty() || selected_vertices.empty()) {
                continue;
            }
            result.normals = existing_normals.size() == vertices.size()
                ? existing_normals
                : std::vector<Vec3>(vertices.size(), {0.0, 0.0, 1.0});
            for (const int vertex_index : selected_vertices) {
                if (vertex_index < 0
                    || static_cast<std::size_t>(vertex_index) >= result.normals.size()
                    || static_cast<std::size_t>(vertex_index) >= source_normals.size()) {
                    continue;
                }
                const Vec3 normal = normalized_vec3_or_zero(source_normals[static_cast<std::size_t>(vertex_index)]);
                if (normal != Vec3{0.0, 0.0, 0.0}) {
                    result.normals[static_cast<std::size_t>(vertex_index)] = normal;
                }
            }
        } else if (operation == "sharpen_normals") {
            std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
            if (selected_faces.empty()) {
                continue;
            }
            result.normals = existing_normals.size() == vertices.size()
                ? existing_normals
                : std::vector<Vec3>(vertices.size(), {0.0, 0.0, 1.0});
            for (const int face_index : selected_faces) {
                if (face_index < 0 || static_cast<std::size_t>(face_index) >= faces.size()) {
                    continue;
                }
                const std::array<int, 3>& face = faces[static_cast<std::size_t>(face_index)];
                const Vec3 normal = face_normal(
                    vertices[static_cast<std::size_t>(face[0])],
                    vertices[static_cast<std::size_t>(face[1])],
                    vertices[static_cast<std::size_t>(face[2])]
                );
                for (const int vertex_index : face) {
                    result.normals[static_cast<std::size_t>(vertex_index)] = normal;
                }
            }
        } else if (operation == "flip_normals") {
            std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
            if (selected_faces.empty()) {
                continue;
            }
            result.faces = faces;
            for (const int face_index : selected_faces) {
                if (face_index >= 0 && static_cast<std::size_t>(face_index) < result.faces.size()) {
                    std::swap(result.faces[static_cast<std::size_t>(face_index)][1], result.faces[static_cast<std::size_t>(face_index)][2]);
                }
            }
            if (bool_or(item.get("selected_all_faces"), false) && existing_normals.size() == vertices.size()) {
                result.normals.reserve(existing_normals.size());
                for (const Vec3& normal : existing_normals) {
                    result.normals.push_back({-normal[0], -normal[1], -normal[2]});
                }
            } else {
                result.normals = compute_smooth_normals(vertices, result.faces);
            }
        } else {
            result.normals = compute_smooth_normals(vertices, faces);
        }
        if (existing_normals.size() == result.normals.size()) {
            for (std::size_t normal_index = 0; normal_index < result.normals.size(); ++normal_index) {
                if (!same_vec3(existing_normals[normal_index], result.normals[normal_index])) {
                    result.changed_vertices.push_back(static_cast<int>(normal_index));
                }
            }
        } else {
            result.changed_vertices.reserve(result.normals.size());
            for (std::size_t normal_index = 0; normal_index < result.normals.size(); ++normal_index) {
                result.changed_vertices.push_back(static_cast<int>(normal_index));
            }
        }
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            if (result.faces.empty()) {
                if (session->vertices.size() == vertices.size()) {
                    session->normals = result.normals;
                }
            } else if (session->vertices.size() == vertices.size()) {
                session->faces = result.faces;
                session->normals = result.normals;
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

void populate_auto_uv_remapped_channels(
    SubmeshAutoUvResult& result,
    const JsonValue& item,
    const std::vector<Vec3>& vertices
) {
    if (result.vertex_remap.empty()) return;
    result.vertices = copy_values_by_vertex_remap(vertices, result.vertex_remap);
    if (!result.normals_path.empty()) {
        result.normals = copy_values_by_vertex_remap(mesh_normals_from_item(item), result.vertex_remap);
        if (result.normals.size() != result.vertices.size() && result.vertices.size() == result.vertex_remap.size()) {
            result.normals = compute_smooth_normals(result.vertices, result.faces);
        }
    }
    if (!result.tangents_path.empty()) {
        result.tangents = copy_values_by_vertex_remap(mesh_tangents_from_item(item), result.vertex_remap);
    }
    if (!result.tangent_signs_path.empty()) {
        result.tangent_signs = copy_values_by_vertex_remap(mesh_tangent_signs_from_item(item), result.vertex_remap);
    }
    if (!result.bone_counts_path.empty() && !result.bone_indices_path.empty() && !result.bone_weights_path.empty()) {
        result.bones = copy_bones_by_vertex_remap(mesh_bones_from_item(item), result.vertex_remap);
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
        result.source_vertex_map = copy_values_by_vertex_remap(source_vertex_map, result.vertex_remap);
    }
    if (!result.source_vertex_offsets_path.empty()) {
        std::vector<int> source_vertex_offsets = source_vertex_offsets_from_item(item);
        if (source_vertex_offsets.empty()) {
            if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                source_vertex_offsets = session->source_vertex_offsets;
            }
        }
        result.source_vertex_offsets = copy_values_by_vertex_remap(source_vertex_offsets, result.vertex_remap);
    }
}

std::vector<SubmeshAutoUvResult> run_auto_uv(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    int resolution = int_or(root.get("atlas_size"), 0);
    int padding = 0;
    const JsonValue* auto_uv = root.get("auto_uv");
    if (auto_uv != nullptr && auto_uv->type == JsonValue::Type::Object) {
        resolution = int_or(auto_uv->get("resolution"), resolution);
        padding = int_or(auto_uv->get("padding"), padding);
    }
    if (resolution < 0) {
        resolution = 0;
    }
    if (padding < 0) {
        padding = 0;
    }

    std::vector<SubmeshAutoUvResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshAutoUvResult result;
        result.index = int_or(item.get("index"), -1);
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.vertex_remap_path = string_or(item.get("vertex_remap_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.tangents_path = string_or(item.get("tangents_output_path"), "");
        result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        result.input_vertex_count = static_cast<int>(vertices.size());
        result.input_face_count = static_cast<int>(faces.size());
        if (result.index < 0 || vertices.empty() || faces.empty()) {
            continue;
        }

        std::vector<float> positions;
        positions.reserve(vertices.size() * 3);
        for (const Vec3& vertex : vertices) {
            positions.push_back(static_cast<float>(vertex[0]));
            positions.push_back(static_cast<float>(vertex[1]));
            positions.push_back(static_cast<float>(vertex[2]));
        }
        std::vector<uint32_t> indices;
        indices.reserve(faces.size() * 3);
        for (const auto& face : faces) {
            indices.push_back(static_cast<uint32_t>(face[0]));
            indices.push_back(static_cast<uint32_t>(face[1]));
            indices.push_back(static_cast<uint32_t>(face[2]));
        }

        xatlas::Atlas* atlas = xatlas::Create();
        xatlas::MeshDecl mesh_decl;
        mesh_decl.vertexPositionData = positions.data();
        mesh_decl.vertexPositionStride = sizeof(float) * 3;
        mesh_decl.vertexCount = static_cast<uint32_t>(vertices.size());
        mesh_decl.indexData = indices.data();
        mesh_decl.indexCount = static_cast<uint32_t>(indices.size());
        mesh_decl.indexFormat = xatlas::IndexFormat::UInt32;
        const xatlas::AddMeshError add_error = xatlas::AddMesh(atlas, mesh_decl);
        if (add_error == xatlas::AddMeshError::Success) {
            xatlas::ChartOptions chart_options;
            xatlas::PackOptions pack_options;
            pack_options.resolution = static_cast<uint32_t>(resolution);
            pack_options.padding = static_cast<uint32_t>(padding);
            xatlas::Generate(atlas, chart_options, pack_options);
            if (atlas->meshCount > 0) {
                const xatlas::Mesh& mesh = atlas->meshes[0];
                result.output_vertex_count = static_cast<int>(mesh.vertexCount);
                result.output_face_count = static_cast<int>(mesh.indexCount / 3);
                result.chart_count = static_cast<int>(mesh.chartCount);
                result.uvs.reserve(mesh.vertexCount);
                result.vertex_remap.reserve(mesh.vertexCount);
                const double width = atlas->width > 0 ? static_cast<double>(atlas->width) : 1.0;
                const double height = atlas->height > 0 ? static_cast<double>(atlas->height) : 1.0;
                for (uint32_t i = 0; i < mesh.vertexCount; ++i) {
                    const xatlas::Vertex& vertex = mesh.vertexArray[i];
                    result.uvs.push_back({static_cast<double>(vertex.uv[0]) / width, static_cast<double>(vertex.uv[1]) / height});
                    result.vertex_remap.push_back(static_cast<int>(vertex.xref));
                }
                result.faces.reserve(mesh.indexCount / 3);
                for (uint32_t i = 0; i + 2 < mesh.indexCount; i += 3) {
                    result.faces.push_back({
                        static_cast<int>(mesh.indexArray[i]),
                        static_cast<int>(mesh.indexArray[i + 1]),
                        static_cast<int>(mesh.indexArray[i + 2]),
                    });
                }
                bool vertex_remap_identity = result.vertex_remap.size() == vertices.size();
                if (vertex_remap_identity) {
                    for (std::size_t vertex_index = 0; vertex_index < result.vertex_remap.size(); ++vertex_index) {
                        if (result.vertex_remap[vertex_index] != static_cast<int>(vertex_index)) {
                            vertex_remap_identity = false;
                            break;
                        }
                    }
                }
                result.topology_changed = result.output_vertex_count != result.input_vertex_count
                    || result.output_face_count != result.input_face_count
                    || !vertex_remap_identity
                    || result.faces != faces;
                const std::vector<Vec2> existing_uvs = mesh_uvs_from_item(item);
                if (result.topology_changed || existing_uvs.size() != static_cast<std::size_t>(result.input_vertex_count)) {
                    result.changed_vertices.reserve(result.uvs.size());
                    for (std::size_t vertex_index = 0; vertex_index < result.uvs.size(); ++vertex_index) {
                        result.changed_vertices.push_back(static_cast<int>(vertex_index));
                    }
                } else {
                    for (std::size_t vertex_index = 0; vertex_index < result.uvs.size(); ++vertex_index) {
                        const int old_index = vertex_index < result.vertex_remap.size() ? result.vertex_remap[vertex_index] : -1;
                        if (old_index < 0
                            || static_cast<std::size_t>(old_index) >= existing_uvs.size()
                            || !same_vec2(existing_uvs[static_cast<std::size_t>(old_index)], result.uvs[vertex_index])) {
                            result.changed_vertices.push_back(static_cast<int>(vertex_index));
                        }
                    }
                }
                populate_auto_uv_remapped_channels(result, item, vertices);
            }
        } else {
            result.status = "error";
            result.error = xatlas::StringForEnum(add_error);
        }
        xatlas::Destroy(atlas);
        results.push_back(std::move(result));
    }
    return results;
}

Vec3 add_vec3(const Vec3& left, const Vec3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 sub_vec3(const Vec3& left, const Vec3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 scale_vec3(const Vec3& value, double scale) {
    return {value[0] * scale, value[1] * scale, value[2] * scale};
}

double dot_vec3(const Vec3& left, const Vec3& right) {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

Vec3 normalized_vec3(const Vec3& value, const Vec3& fallback) {
    const double length = std::sqrt(dot_vec3(value, value));
    if (length > 1e-8 && std::isfinite(length)) {
        return {value[0] / length, value[1] / length, value[2] / length};
    }
    return fallback;
}

double length_vec3(const Vec3& value) {
    return std::sqrt(dot_vec3(value, value));
}

std::vector<std::set<int>> build_vertex_adjacency(
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
) {
    std::vector<std::set<int>> adjacency(vertex_count);
    for (const auto& face : faces) {
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        adjacency[static_cast<std::size_t>(a)].insert(b);
        adjacency[static_cast<std::size_t>(a)].insert(c);
        adjacency[static_cast<std::size_t>(b)].insert(a);
        adjacency[static_cast<std::size_t>(b)].insert(c);
        adjacency[static_cast<std::size_t>(c)].insert(a);
        adjacency[static_cast<std::size_t>(c)].insert(b);
    }
    return adjacency;
}

std::vector<SubmeshSelectionResult> run_selection_edit(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const JsonValue* selection = root.get("selection");
    if (selection == nullptr || selection->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing selection object");
    }
    std::string operation = string_or(selection->get("operation"), "");
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const int iterations = std::max(0, int_or(selection->get("iterations"), int_or(selection->get("steps"), 1)));
    const bool all_operation = operation == "all";
    const bool invert_operation = operation == "invert";
    std::vector<SubmeshSelectionResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        if (submesh_index < 0 || vertex_count == 0) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::set<int> selected = selected_vertices_from_edit_domains(item, vertex_count, faces);
        if (selected.empty() && !invert_operation && !all_operation) {
            continue;
        }
        if (all_operation) {
            selected.clear();
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                selected.insert(static_cast<int>(vertex_index));
            }
        } else if (invert_operation) {
            std::set<int> inverted;
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                if (selected.find(static_cast<int>(vertex_index)) == selected.end()) {
                    inverted.insert(static_cast<int>(vertex_index));
                }
            }
            selected = std::move(inverted);
        } else {
            const std::vector<std::set<int>> adjacency = build_vertex_adjacency(vertex_count, faces);
            for (int iteration = 0; iteration < iterations; ++iteration) {
                if (operation == "grow") {
                    std::set<int> next = selected;
                    for (const int vertex_index : selected) {
                        if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < adjacency.size()) {
                            next.insert(adjacency[static_cast<std::size_t>(vertex_index)].begin(), adjacency[static_cast<std::size_t>(vertex_index)].end());
                        }
                    }
                    selected = std::move(next);
                } else if (operation == "shrink") {
                    std::set<int> next;
                    for (const int vertex_index : selected) {
                        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= adjacency.size()) {
                            continue;
                        }
                        const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(vertex_index)];
                        bool keep = neighbors.empty();
                        if (!keep) {
                            keep = true;
                            for (const int neighbor : neighbors) {
                                if (selected.find(neighbor) == selected.end()) {
                                    keep = false;
                                    break;
                                }
                            }
                        }
                        if (keep) {
                            next.insert(vertex_index);
                        }
                    }
                    selected = std::move(next);
                } else if (operation == "smooth") {
                    std::set<int> next;
                    for (std::size_t vertex_index = 0; vertex_index < adjacency.size(); ++vertex_index) {
                        const std::set<int>& neighbors = adjacency[vertex_index];
                        const bool is_selected = selected.find(static_cast<int>(vertex_index)) != selected.end();
                        if (neighbors.empty()) {
                            if (is_selected) {
                                next.insert(static_cast<int>(vertex_index));
                            }
                            continue;
                        }
                        int selected_neighbors = 0;
                        for (const int neighbor : neighbors) {
                            if (selected.find(neighbor) != selected.end()) {
                                ++selected_neighbors;
                            }
                        }
                        const double ratio = static_cast<double>(selected_neighbors) / static_cast<double>(std::max<std::size_t>(1, neighbors.size()));
                        if ((is_selected && ratio >= 0.25) || (!is_selected && ratio >= 0.65)) {
                            next.insert(static_cast<int>(vertex_index));
                        }
                    }
                    selected = std::move(next);
                } else {
                    throw std::runtime_error("unsupported selection operation: " + operation);
                }
            }
        }
        if (!selected.empty()) {
            SubmeshSelectionResult result;
            result.index = submesh_index;
            result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "");
            result.selected_vertices.assign(selected.begin(), selected.end());
            results.push_back(std::move(result));
        }
    }
    return results;
}
