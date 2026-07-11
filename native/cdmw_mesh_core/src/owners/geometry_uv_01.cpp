UvTransform uv_transform_from_json(const JsonValue& root) {
    const JsonValue* transform = root.get("uv_transform");
    if (transform == nullptr || transform->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing uv_transform object");
    }
    UvTransform result;
    result.offset = vec2_or(transform->get("offset"), result.offset);
    result.scale = vec2_or(transform->get("scale"), result.scale);
    result.rotate = number_or(transform->get("rotate"), 0.0);
    result.flip_u = bool_or(transform->get("flip_u"), false);
    result.flip_v = bool_or(transform->get("flip_v"), false);
    result.pivot = vec2_or(transform->get("pivot"), result.pivot);
    if (transform->get("input_bounds_min") != nullptr || transform->get("input_bounds_max") != nullptr) {
        result.validate_input_bounds = true;
        result.input_bounds_min = vec2_or(transform->get("input_bounds_min"), result.input_bounds_min);
        result.input_bounds_max = vec2_or(transform->get("input_bounds_max"), result.input_bounds_max);
    }
    result.clamp_input_uv = bool_or(transform->get("clamp_input_uv"), false);
    result.input_clamp_min = vec2_or(transform->get("input_clamp_min"), result.input_clamp_min);
    result.input_clamp_max = vec2_or(transform->get("input_clamp_max"), result.input_clamp_max);
    result.projection = lower_ascii(string_or(transform->get("projection"), result.projection));
    result.plane = lower_ascii(string_or(transform->get("plane"), result.plane));
    result.axis = lower_ascii(string_or(transform->get("axis"), result.axis));
    result.initialize_missing_uvs = bool_or(transform->get("initialize_missing_uvs"), false);
    result.normalize = bool_or(transform->get("normalize"), false);
    result.target_min = vec2_or(transform->get("target_min"), result.target_min);
    result.target_max = vec2_or(transform->get("target_max"), result.target_max);
    result.pack = bool_or(transform->get("pack"), false);
    result.pack_columns = std::max(0, int_or(transform->get("pack_columns"), 0));
    result.pack_padding = std::max(0.0, number_or(transform->get("padding"), number_or(transform->get("pack_padding"), result.pack_padding)));
    result.uv_island = bool_or(transform->get("uv_island"), bool_or(transform->get("island"), false));
    const std::string mode = lower_ascii(string_or(transform->get("mode"), ""));
    if (mode == "island" || mode == "uv_island") {
        result.uv_island = true;
    }
    result.snap_step = vec2_or(transform->get("snap_step"), result.snap_step);
    if (result.snap_step[0] <= 0.0 || result.snap_step[1] <= 0.0) {
        const double snap_grid = number_or(
            transform->get("snap_grid"),
            number_or(transform->get("snap_increment"), number_or(transform->get("grid"), 0.0))
        );
        if (snap_grid > 0.0) {
            result.snap_step = {snap_grid, snap_grid};
        }
    }
    if (bool_or(transform->get("pixel_snap"), bool_or(transform->get("snap_pixels"), false))) {
        const Vec2 texture_size = vec2_or(transform->get("texture_size"), {0.0, 0.0});
        if (texture_size[0] > 0.0 && texture_size[1] > 0.0) {
            result.snap_step = {1.0 / texture_size[0], 1.0 / texture_size[1]};
        }
    }
    result.snap = bool_or(transform->get("snap"), result.snap_step[0] > 0.0 || result.snap_step[1] > 0.0);
    uv_align_from_json(
        transform->get("align_u"),
        result.has_align_u,
        result.align_u_is_number,
        result.align_u_number,
        result.align_u_mode
    );
    uv_align_from_json(
        transform->get("align_v"),
        result.has_align_v,
        result.align_v_is_number,
        result.align_v_number,
        result.align_v_mode
    );
    return result;
}

double snap_value(double value, double increment) {
    if (increment <= 0.0) {
        return value;
    }
    const double snapped = std::nearbyint(value / increment) * increment;
    return std::abs(snapped) < 1e-12 ? 0.0 : snapped;
}

Vec3 snap_vertex(const Vec3& vertex, double increment) {
    return {
        snap_value(vertex[0], increment),
        snap_value(vertex[1], increment),
        snap_value(vertex[2], increment),
    };
}

Vec3 transform_vertex(const Vec3& vertex, const Transform& transform) {
    double x = (vertex[0] - transform.pivot[0]) * transform.scale[0];
    double y = (vertex[1] - transform.pivot[1]) * transform.scale[1];
    double z = (vertex[2] - transform.pivot[2]) * transform.scale[2];
    const double rx = transform.rotate[0] * 3.14159265358979323846 / 180.0;
    const double ry = transform.rotate[1] * 3.14159265358979323846 / 180.0;
    const double rz = transform.rotate[2] * 3.14159265358979323846 / 180.0;
    if (std::abs(rx) > 1e-8) {
        const double c = std::cos(rx);
        const double s = std::sin(rx);
        const double next_y = y * c - z * s;
        const double next_z = y * s + z * c;
        y = next_y;
        z = next_z;
    }
    if (std::abs(ry) > 1e-8) {
        const double c = std::cos(ry);
        const double s = std::sin(ry);
        const double next_x = x * c + z * s;
        const double next_z = -x * s + z * c;
        x = next_x;
        z = next_z;
    }
    if (std::abs(rz) > 1e-8) {
        const double c = std::cos(rz);
        const double s = std::sin(rz);
        const double next_x = x * c - y * s;
        const double next_y = x * s + y * c;
        x = next_x;
        y = next_y;
    }
    return snap_vertex(
        {
            transform.pivot[0] + x + transform.translate[0],
            transform.pivot[1] + y + transform.translate[1],
            transform.pivot[2] + z + transform.translate[2],
        },
        transform.snap
    );
}

bool same_vec3(const Vec3& left, const Vec3& right) {
    return std::abs(left[0] - right[0]) <= 1e-8
        && std::abs(left[1] - right[1]) <= 1e-8
        && std::abs(left[2] - right[2]) <= 1e-8;
}

double distance_squared_vec3(const Vec3& left, const Vec3& right) {
    const double dx = left[0] - right[0];
    const double dy = left[1] - right[1];
    const double dz = left[2] - right[2];
    return dx * dx + dy * dy + dz * dz;
}

Vec3 average_vertices(const std::vector<Vec3>& vertices, const std::vector<int>& indices) {
    Vec3 sum{0.0, 0.0, 0.0};
    if (indices.empty()) {
        return sum;
    }
    for (const int index : indices) {
        const Vec3& vertex = vertices[static_cast<std::size_t>(index)];
        sum[0] += vertex[0];
        sum[1] += vertex[1];
        sum[2] += vertex[2];
    }
    const double scale = 1.0 / static_cast<double>(indices.size());
    return {sum[0] * scale, sum[1] * scale, sum[2] * scale};
}

void accumulate_transform_selection_pivot(const JsonValue& item, const Transform& transform, Vec3& sum, std::size_t& count) {
    if (item.type != JsonValue::Type::Object) {
        return;
    }
    const int sparse_vertex_count = int_or(item.get("vertex_count"), 0);
    const std::map<int, Vec3> sparse_vertices = indexed_vertices_from_binary_or_json(item, sparse_vertex_count);
    const bool sparse_input = !sparse_vertices.empty() && !transform.mirror_x;
    if (sparse_input) {
        std::set<int> selected = selected_vertices_from_binary_or_json(item, static_cast<std::size_t>(sparse_vertex_count));
        if (selected.empty()) {
            for (const auto& sparse_item : sparse_vertices) {
                selected.insert(sparse_item.first);
            }
        }
        for (const int vertex_index : selected) {
            const auto found = sparse_vertices.find(vertex_index);
            if (found == sparse_vertices.end()) {
                continue;
            }
            sum[0] += found->second[0];
            sum[1] += found->second[1];
            sum[2] += found->second[2];
            ++count;
        }
        return;
    }

    if (const MeshSessionSubmesh* resident = mesh_session_submesh_for_item(item)) {
        const std::set<int> selected = selected_vertices_from_edit_domains(
            item,
            resident->vertices.size(),
            resident->faces
        );
        for (const int vertex_index : selected) {
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= resident->vertices.size()) {
                continue;
            }
            const Vec3& vertex = resident->vertices[static_cast<std::size_t>(vertex_index)];
            sum[0] += vertex[0];
            sum[1] += vertex[1];
            sum[2] += vertex[2];
            ++count;
        }
        return;
    }

    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    if (vertices.empty()) {
        return;
    }
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    const std::set<int> selected = selected_vertices_from_edit_domains(item, vertices.size(), faces);
    for (const int vertex_index : selected) {
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
            continue;
        }
        const Vec3& vertex = vertices[static_cast<std::size_t>(vertex_index)];
        sum[0] += vertex[0];
        sum[1] += vertex[1];
        sum[2] += vertex[2];
        ++count;
    }
}

Vec3 transform_selection_pivot(const JsonValue& submeshes, const Transform& transform) {
    Vec3 sum{0.0, 0.0, 0.0};
    std::size_t count = 0;
    for (const JsonValue& item : submeshes.array_value) {
        accumulate_transform_selection_pivot(item, transform, sum, count);
    }
    if (count == 0) {
        return transform.pivot;
    }
    const double scale = 1.0 / static_cast<double>(count);
    return {sum[0] * scale, sum[1] * scale, sum[2] * scale};
}

std::map<int, int> mirror_pairs_from_json(const JsonValue* value, std::size_t vertex_count);
std::map<int, int> build_x_mirror_pairs_native(const std::vector<Vec3>& vertices);

bool append_resident_sparse_transform(
    const JsonValue& item,
    const Transform& item_transform,
    const std::string& sparse_snapshot_id,
    SubmeshTransformResult& result,
    std::vector<SubmeshTransformResult>& results
) {
    MeshSessionSubmesh* resident = mutable_mesh_session_submesh_for_item(item);
    const bool explicit_sparse_positions = item.get("vertex_positions_binary") != nullptr
        || item.get("vertex_positions") != nullptr;
    if (resident != nullptr && !explicit_sparse_positions && !item_transform.mirror_x) {
        result.sparse = true;
        result.resident_sparse = true;
        const std::size_t vertex_count = resident->vertices.size();
        const std::set<int> selected = selected_vertices_from_edit_domains(item, vertex_count, resident->faces);
        for (const int vertex_index : selected) {
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertex_count) {
                continue;
            }
            const Vec3 old_vertex = resident->vertices[static_cast<std::size_t>(vertex_index)];
            const Vec3 new_vertex = transform_vertex(old_vertex, item_transform);
            if (same_vec3(old_vertex, new_vertex)) {
                continue;
            }
            resident->vertices[static_cast<std::size_t>(vertex_index)] = new_vertex;
            result.changed_vertices.push_back(vertex_index);
            result.before_positions.push_back(old_vertex);
            result.changed_positions.push_back(new_vertex);
            result.changed_source_vertex_ids.push_back(
                resident->source_vertex_map.size() == vertex_count
                    ? resident->source_vertex_map[static_cast<std::size_t>(vertex_index)]
                    : vertex_index
            );
        }
        if (!result.changed_vertices.empty()) {
            result.sparse_snapshot_id = sparse_snapshot_id;
            store_sparse_vertex_snapshot_values(
                sparse_snapshot_id,
                result.index,
                static_cast<int>(vertex_count),
                result.changed_vertices,
                result.before_positions
            );
            resident->tangents.clear();
            resident->tangent_signs.clear();
            if (item_transform.recompute_normals && !resident->faces.empty()) {
                resident->normals = compute_smooth_normals(resident->vertices, resident->faces);
            } else if (item_transform.recompute_normals) {
                resident->normals.clear();
            }
            results.push_back(std::move(result));
        }
        return true;
    }
    return false;
}

Transform mesh_transform_for_item(
    const Transform& transform,
    const JsonValue* screen_drag,
    int submesh_index
) {
    Transform item_transform = transform;
    const bool projected = mesh_editor_has_projection_payload(screen_drag, submesh_index);
    const Vec3 base_translate = projected ? Vec3{0.0, 0.0, 0.0} : transform.translate;
    item_transform.translate = constrain_vec3_axis(
        add_screen_drag_delta(base_translate, screen_drag, &transform.pivot, submesh_index),
        transform.axis,
        {0.0, 0.0, 0.0}
    );
    return item_transform;
}

SubmeshTransformResult mesh_transform_result_for_item(const JsonValue& item) {
    SubmeshTransformResult result;
    result.index = int_or(item.get("index"), -1);
    result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
    result.changed_positions_path = string_or(item.get("changed_positions_output_path"), "");
    result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
    return result;
}

std::vector<SubmeshTransformResult> run_transform(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    Transform transform = transform_from_json(root);
    if (transform.pivot_from_selection) {
        transform.pivot = transform_selection_pivot(*submeshes, transform);
    }
    const JsonValue* transform_json = root.get("transform");
    const JsonValue* screen_drag = transform_json != nullptr && transform_json->type == JsonValue::Type::Object
        ? transform_json->get("screen_drag")
        : nullptr;
    std::vector<SubmeshTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result = mesh_transform_result_for_item(item);
        const Transform item_transform = mesh_transform_for_item(transform, screen_drag, result.index);
        if (append_resident_sparse_transform(
            item,
            item_transform,
            sparse_snapshot_id,
            result,
            results
        )) {
            continue;
        }
        const int sparse_vertex_count = int_or(item.get("vertex_count"), 0);
        const std::map<int, Vec3> sparse_vertices = indexed_vertices_from_binary_or_json(item, sparse_vertex_count);
        const bool sparse_input = !sparse_vertices.empty() && !item_transform.mirror_x;
        const bool sparse_output = bool_or(item.get("sparse_output"), false);
        result.sparse = sparse_input;
        if (!sparse_input) {
            result.vertices = mesh_vertices_from_item(item);
        }
        const std::size_t vertex_count = sparse_input ? static_cast<std::size_t>(sparse_vertex_count) : result.vertices.size();
        result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertex_count);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::set<int> selected = selected_vertices_from_edit_domains(item, vertex_count, faces);
        if (sparse_input && selected.empty()) {
            for (const auto& sparse_item : sparse_vertices) {
                selected.insert(sparse_item.first);
            }
        }
        if (result.index < 0 || vertex_count == 0 || selected.empty()) {
            continue;
        }
        if (sparse_input) {
            for (const int vertex_index : selected) {
                const auto found = sparse_vertices.find(vertex_index);
                if (found == sparse_vertices.end()) {
                    continue;
                }
                const Vec3 old_vertex = found->second;
                const Vec3 new_vertex = transform_vertex(old_vertex, item_transform);
                if (!same_vec3(old_vertex, new_vertex)) {
                    result.changed_vertices.push_back(vertex_index);
                    result.changed_positions.push_back(new_vertex);
                    result.before_positions.push_back(old_vertex);
                }
            }
            if (!result.changed_vertices.empty()) {
                result.sparse_snapshot_id = sparse_snapshot_id;
                store_sparse_vertex_snapshot_values(
                    sparse_snapshot_id,
                    result.index,
                    sparse_vertex_count,
                    result.changed_vertices,
                    result.before_positions
                );
                results.push_back(std::move(result));
            }
            continue;
        }
        if (result.vertices.empty()) {
            continue;
        }
        std::map<int, bool> target_vertices;
        for (const int vertex_index : selected) {
            target_vertices[vertex_index] = false;
        }
        if (item_transform.mirror_x) {
            std::map<int, int> mirror_pairs = mirror_pairs_from_json(item.get("mirror_pairs"), result.vertices.size());
            if (mirror_pairs.empty()) {
                mirror_pairs = build_x_mirror_pairs_native(result.vertices);
            }
            for (const int vertex_index : selected) {
                const auto found = mirror_pairs.find(vertex_index);
                if (found != mirror_pairs.end()) {
                    target_vertices.emplace(found->second, true);
                }
            }
        }
        for (const auto& target : target_vertices) {
            const int vertex_index = target.first;
            const Vec3 old_vertex = result.vertices[static_cast<std::size_t>(vertex_index)];
            Transform local_transform = item_transform;
            if (target.second) {
                local_transform.translate[0] = -local_transform.translate[0];
            }
            const Vec3 new_vertex = transform_vertex(old_vertex, local_transform);
            if (!same_vec3(old_vertex, new_vertex)) {
                result.vertices[static_cast<std::size_t>(vertex_index)] = new_vertex;
                result.changed_vertices.push_back(vertex_index);
                result.before_positions.push_back(old_vertex);
                result.changed_positions.push_back(new_vertex);
            }
        }
        if (sparse_output) {
            result.sparse = true;
            result.changed_positions.clear();
            result.changed_positions.reserve(result.changed_vertices.size());
            for (const int vertex_index : result.changed_vertices) {
                if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < result.vertices.size()) {
                    result.changed_positions.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                }
            }
        }
        if (!result.changed_vertices.empty()) {
            result.sparse_snapshot_id = sparse_snapshot_id;
            store_sparse_vertex_snapshot_values(
                sparse_snapshot_id,
                result.index,
                static_cast<int>(result.vertices.size()),
                result.changed_vertices,
                result.before_positions
            );
            if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
                if (session->vertices.size() == result.vertices.size()) {
                    session->vertices = result.vertices;
                    session->tangents.clear();
                    session->tangent_signs.clear();
                    if (item_transform.recompute_normals && !session->faces.empty()) {
                        session->normals = compute_smooth_normals(session->vertices, session->faces);
                    } else if (item_transform.recompute_normals) {
                        session->normals.clear();
                    }
                }
            }
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<SubmeshTransformResult> run_restore_vertices(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    std::vector<SubmeshTransformResult> results;
    std::map<int, std::set<int>> restored_indices_by_submesh;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.changed_positions_path = string_or(item.get("changed_positions_output_path"), "");
        result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
        result.sparse = true;
        if (result.index < 0) {
            continue;
        }
        MeshSessionSubmesh* resident = mutable_mesh_session_submesh_for_item(item);
        const bool explicit_vertices = item.get("vertices_binary") != nullptr || item.get("vertices") != nullptr;
        if (resident != nullptr && !explicit_vertices) {
            result.resident_sparse = true;
            const int vertex_count = static_cast<int>(resident->vertices.size());
            std::map<int, Vec3> restore_positions = sparse_vertex_snapshot_positions_from_item(item, vertex_count);
            if (restore_positions.empty()) {
                restore_positions = indexed_vertices_from_binary_or_json(item, vertex_count);
            }
            for (const auto& restore_item : restore_positions) {
                const int vertex_index = restore_item.first;
                if (vertex_index < 0 || vertex_index >= vertex_count) {
                    continue;
                }
                std::set<int>& restored_indices = restored_indices_by_submesh[result.index];
                if (!restored_indices.insert(vertex_index).second) {
                    continue;
                }
                const Vec3 old_vertex = resident->vertices[static_cast<std::size_t>(vertex_index)];
                if (same_vec3(old_vertex, restore_item.second)) {
                    continue;
                }
                resident->vertices[static_cast<std::size_t>(vertex_index)] = restore_item.second;
                result.changed_vertices.push_back(vertex_index);
                result.changed_positions.push_back(restore_item.second);
                result.before_positions.push_back(old_vertex);
                result.changed_source_vertex_ids.push_back(
                    resident->source_vertex_map.size() == resident->vertices.size()
                        ? resident->source_vertex_map[static_cast<std::size_t>(vertex_index)]
                        : vertex_index
                );
            }
            if (!result.changed_vertices.empty()) {
                result.sparse_snapshot_id = sparse_snapshot_id;
                store_sparse_vertex_snapshot_values(
                    sparse_snapshot_id,
                    result.index,
                    vertex_count,
                    result.changed_vertices,
                    result.before_positions
                );
                resident->normals.clear();
                results.push_back(std::move(result));
            }
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const int explicit_vertex_count = int_or(item.get("vertex_count"), -1);
        const std::size_t vertex_count = vertices.empty() && explicit_vertex_count > 0
            ? static_cast<std::size_t>(explicit_vertex_count)
            : vertices.size();
        if (vertex_count == 0 || vertices.size() != vertex_count) {
            continue;
        }
        result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertex_count);
        std::map<int, Vec3> restore_positions = sparse_vertex_snapshot_positions_from_item(
            item,
            static_cast<int>(vertex_count)
        );
        if (restore_positions.empty()) {
            restore_positions = indexed_vertices_from_binary_or_json(
                item,
                static_cast<int>(vertex_count)
            );
        }
        if (restore_positions.empty()) {
            continue;
        }
        for (const auto& restore_item : restore_positions) {
            const int vertex_index = restore_item.first;
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
                continue;
            }
            std::set<int>& restored_indices = restored_indices_by_submesh[result.index];
            if (restored_indices.find(vertex_index) != restored_indices.end()) {
                continue;
            }
            restored_indices.insert(vertex_index);
            const Vec3 old_vertex = vertices[static_cast<std::size_t>(vertex_index)];
            const Vec3 restored_vertex = restore_item.second;
            if (!same_vec3(old_vertex, restored_vertex)) {
                vertices[static_cast<std::size_t>(vertex_index)] = restored_vertex;
                result.changed_vertices.push_back(vertex_index);
                result.changed_positions.push_back(restored_vertex);
                result.before_positions.push_back(old_vertex);
            }
        }
        if (result.changed_vertices.empty()) {
            continue;
        }
        result.sparse_snapshot_id = sparse_snapshot_id;
        store_sparse_vertex_snapshot_values(
            sparse_snapshot_id,
            result.index,
            static_cast<int>(vertices.size()),
            result.changed_vertices,
            result.before_positions
        );
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            if (session->vertices.size() == vertices.size()) {
                session->vertices = vertices;
                session->normals.clear();
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshTransformResult> run_snapshot_vertices(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    std::vector<SubmeshTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
        result.sparse = true;
        if (result.index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const int explicit_vertex_count = int_or(item.get("vertex_count"), -1);
        const std::size_t vertex_count = vertices.empty() && explicit_vertex_count > 0
            ? static_cast<std::size_t>(explicit_vertex_count)
            : vertices.size();
        if (vertex_count == 0 || vertices.size() != vertex_count) {
            continue;
        }
        const std::vector<int> requested = int_vector_from_binary_or_json(
            item,
            "vertex_indices_binary",
            "vertex_indices",
            "vertex_index_start",
            "vertex_index_count"
        );
        std::set<int> seen;
        for (const int vertex_index : requested) {
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
                continue;
            }
            if (seen.find(vertex_index) != seen.end()) {
                continue;
            }
            seen.insert(vertex_index);
            result.changed_vertices.push_back(vertex_index);
            result.before_positions.push_back(vertices[static_cast<std::size_t>(vertex_index)]);
        }
        if (!result.changed_vertices.empty()) {
            result.sparse_snapshot_id = sparse_snapshot_id;
            store_sparse_vertex_snapshot_values(
                sparse_snapshot_id,
                result.index,
                static_cast<int>(vertex_count),
                result.changed_vertices,
                result.before_positions
            );
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<Vec2> remap_vec2_by_index_map(const std::vector<Vec2>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<Vec2> output(output_count, {0.0, 0.0});
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

std::vector<Vec3> remap_vec3_by_index_map(const std::vector<Vec3>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<Vec3> output(output_count, {0.0, 0.0, 0.0});
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

std::vector<double> remap_double_by_index_map(const std::vector<double>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<double> output(output_count, 0.0);
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

std::vector<int> remap_int_by_index_map(const std::vector<int>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<int> output(output_count, -1);
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

BoneAssignments remap_bones_by_index_map(const BoneAssignments& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (!valid_bone_assignments(input) || input.indices.size() != index_map.size()) {
        return {};
    }
    BoneAssignments output;
    output.indices.resize(output_count);
    output.weights.resize(output_count);
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output.indices[static_cast<std::size_t>(new_index)] = input.indices[old_index];
        output.weights[static_cast<std::size_t>(new_index)] = input.weights[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

template <typename T>
std::vector<T> copy_values_by_vertex_remap(const std::vector<T>& input, const std::vector<int>& remap) {
    if (input.empty() || remap.empty()) {
        return {};
    }
    std::vector<T> output;
    output.reserve(remap.size());
    for (const int old_index : remap) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= input.size()) {
            return {};
        }
        output.push_back(input[static_cast<std::size_t>(old_index)]);
    }
    return output;
}
