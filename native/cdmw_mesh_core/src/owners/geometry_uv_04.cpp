std::vector<Vec2> vec2_array_from_json(const JsonValue* value) {
    std::vector<Vec2> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        Vec2 point{
            number_or(&item.array_value[0], 0.0),
            number_or(&item.array_value[1], 0.0),
        };
        if (std::isfinite(point[0]) && std::isfinite(point[1])) {
            result.push_back(point);
        }
    }
    return result;
}

bool uv_point_on_segment(const Vec2& point, const Vec2& left, const Vec2& right) {
    const double cross = (point[1] - left[1]) * (right[0] - left[0]) - (point[0] - left[0]) * (right[1] - left[1]);
    if (std::abs(cross) > 1.0e-9) {
        return false;
    }
    return std::min(left[0], right[0]) - 1.0e-9 <= point[0]
        && point[0] <= std::max(left[0], right[0]) + 1.0e-9
        && std::min(left[1], right[1]) - 1.0e-9 <= point[1]
        && point[1] <= std::max(left[1], right[1]) + 1.0e-9;
}

bool uv_point_in_polygon(const Vec2& point, const std::vector<Vec2>& polygon) {
    if (polygon.size() < 3) {
        return false;
    }
    bool inside = false;
    Vec2 previous = polygon.back();
    for (const Vec2& current : polygon) {
        if (uv_point_on_segment(point, previous, current)) {
            return true;
        }
        const bool crosses = (current[1] > point[1]) != (previous[1] > point[1]);
        if (crosses) {
            const double slope_x = (previous[0] - current[0]) * (point[1] - current[1]) / (previous[1] - current[1]) + current[0];
            if (point[0] <= slope_x) {
                inside = !inside;
            }
        }
        previous = current;
    }
    return inside;
}

std::vector<SubmeshUvSelectionResult> run_uv_selection(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::string mode = string_or(root.get("mode"), "region");
    std::transform(mode.begin(), mode.end(), mode.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const Vec2 start = vec2_or(root.get("uv_min"), {0.0, 0.0});
    const Vec2 end = vec2_or(root.get("uv_max"), {0.0, 0.0});
    const double min_u = std::min(start[0], end[0]);
    const double max_u = std::max(start[0], end[0]);
    const double min_v = std::min(start[1], end[1]);
    const double max_v = std::max(start[1], end[1]);
    const std::vector<Vec2> polygon = vec2_array_from_json(root.get("points"));
    if (mode == "lasso" && polygon.size() < 3) {
        return {};
    }
    if (mode != "region" && mode != "lasso") {
        throw std::runtime_error("unsupported uv selection mode: " + mode);
    }

    std::vector<SubmeshUvSelectionResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (submesh_index < 0 || vertex_count == 0 || uvs.size() != vertex_count) {
            continue;
        }
        std::vector<int> selected;
        selected.reserve(uvs.size());
        for (std::size_t vertex_index = 0; vertex_index < uvs.size(); ++vertex_index) {
            const Vec2& uv = uvs[vertex_index];
            const bool contained = mode == "lasso"
                ? uv_point_in_polygon(uv, polygon)
                : (min_u <= uv[0] && uv[0] <= max_u && min_v <= uv[1] && uv[1] <= max_v);
            if (contained) {
                selected.push_back(static_cast<int>(vertex_index));
            }
        }
        if (selected.empty()) {
            continue;
        }
        SubmeshUvSelectionResult result;
        result.index = submesh_index;
        result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "");
        result.selected_vertices = std::move(selected);
        results.push_back(std::move(result));
    }
    return results;
}

using NativeUvKey = std::array<long long, 2>;
using NativeUvEdgeKey = std::tuple<std::array<int, 2>, NativeUvKey, NativeUvKey>;

NativeUvKey native_uv_key(const Vec2& value) {
    return {
        static_cast<long long>(std::llround(value[0] * 1000000.0)),
        static_cast<long long>(std::llround(value[1] * 1000000.0)),
    };
}

NativeUvEdgeKey native_uv_edge_key(int left, int right, const std::vector<Vec2>& uvs) {
    std::array<int, 2> vertex_edge{std::min(left, right), std::max(left, right)};
    NativeUvKey left_uv = native_uv_key(uvs[static_cast<std::size_t>(left)]);
    NativeUvKey right_uv = native_uv_key(uvs[static_cast<std::size_t>(right)]);
    if (right_uv < left_uv) {
        std::swap(left_uv, right_uv);
    }
    return std::make_tuple(vertex_edge, left_uv, right_uv);
}

std::vector<UvIslandSummaryResult> run_uv_summary(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<UvIslandSummaryResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (submesh_index < 0 || vertex_count == 0 || uvs.size() != vertex_count) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        if (faces.empty()) {
            continue;
        }
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        const std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
        std::set<int> selected_faces;
        for (const int face_index : int_vector_from_binary_or_json(
            item,
            "selected_faces_binary",
            "selected_faces",
            "selected_face_start",
            "selected_face_count"
        )) {
            if (face_index >= 0) {
                selected_faces.insert(face_index);
            }
        }
        const bool source_selected = bool_or(item.get("source_selected"), false);

        std::map<int, std::vector<NativeUvEdgeKey>> face_edges;
        std::map<NativeUvEdgeKey, std::set<int>> edge_faces;
        for (std::size_t face_offset = 0; face_offset < faces.size(); ++face_offset) {
            const std::array<int, 3>& face = faces[face_offset];
            std::vector<NativeUvEdgeKey> edges;
            edges.reserve(3);
            for (int edge_index = 0; edge_index < 3; ++edge_index) {
                const int left = face[static_cast<std::size_t>(edge_index)];
                const int right = face[static_cast<std::size_t>((edge_index + 1) % 3)];
                edges.push_back(native_uv_edge_key(left, right, uvs));
            }
            const int compact_face_index = static_cast<int>(face_offset);
            face_edges[compact_face_index] = edges;
            for (const NativeUvEdgeKey& edge : edges) {
                edge_faces[edge].insert(compact_face_index);
            }
        }

        std::set<int> visited;
        for (std::size_t seed_offset = 0; seed_offset < faces.size(); ++seed_offset) {
            const int seed = static_cast<int>(seed_offset);
            if (visited.find(seed) != visited.end()) {
                continue;
            }
            std::vector<int> pending{seed};
            std::set<int> island_faces;
            while (!pending.empty()) {
                const int face_index = pending.back();
                pending.pop_back();
                if (island_faces.find(face_index) != island_faces.end() || visited.find(face_index) != visited.end()) {
                    continue;
                }
                island_faces.insert(face_index);
                visited.insert(face_index);
                for (const NativeUvEdgeKey& edge : face_edges[face_index]) {
                    const std::set<int>& neighbors = edge_faces[edge];
                    for (const int neighbor : neighbors) {
                        if (island_faces.find(neighbor) == island_faces.end()) {
                            pending.push_back(neighbor);
                        }
                    }
                }
            }

            std::set<int> island_vertices;
            for (const int face_index : island_faces) {
                if (face_index < 0 || static_cast<std::size_t>(face_index) >= faces.size()) {
                    continue;
                }
                const std::array<int, 3>& face = faces[static_cast<std::size_t>(face_index)];
                island_vertices.insert(face[0]);
                island_vertices.insert(face[1]);
                island_vertices.insert(face[2]);
            }
            if (island_vertices.empty()) {
                continue;
            }

            Vec2 uv_min{1.0e300, 1.0e300};
            Vec2 uv_max{-1.0e300, -1.0e300};
            int selected_vertex_count = 0;
            for (const int vertex_index : island_vertices) {
                const Vec2& uv = uvs[static_cast<std::size_t>(vertex_index)];
                uv_min[0] = std::min(uv_min[0], uv[0]);
                uv_min[1] = std::min(uv_min[1], uv[1]);
                uv_max[0] = std::max(uv_max[0], uv[0]);
                uv_max[1] = std::max(uv_max[1], uv[1]);
                if (selected_vertices.find(vertex_index) != selected_vertices.end()) {
                    ++selected_vertex_count;
                }
            }

            int selected_face_count = 0;
            for (const int face_index : island_faces) {
                const int source_face_index = static_cast<std::size_t>(face_index) < source_faces.size()
                    ? source_faces[static_cast<std::size_t>(face_index)]
                    : face_index;
                if (selected_faces.find(source_face_index) != selected_faces.end()) {
                    ++selected_face_count;
                }
            }

            UvIslandSummaryResult result;
            result.index = static_cast<int>(results.size());
            result.submesh_index = submesh_index;
            result.part_name = string_or(item.get("part_name"), std::string("part_") + std::to_string(submesh_index));
            result.material = string_or(item.get("material"), "");
            result.texture = string_or(item.get("texture"), "");
            result.vertex_count = static_cast<int>(island_vertices.size());
            result.face_count = static_cast<int>(island_faces.size());
            result.uv_min = uv_min;
            result.uv_max = uv_max;
            result.selected_vertex_count = selected_vertex_count;
            result.selected_face_count = selected_face_count;
            result.selected = source_selected || selected_vertex_count > 0 || selected_face_count > 0;
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<SubmeshMetadataResult> run_mesh_metadata(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshMetadataResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshMetadataResult result;
        result.index = int_or(item.get("index"), -1);
        if (result.index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        result.vertex_count = vertices.empty()
            ? static_cast<std::size_t>(std::max(0, int_or(item.get("vertex_count"), 0)))
            : vertices.size();
        result.face_count = static_cast<std::size_t>(std::max(0, int_or(item.get("face_count"), 0)));
        if (item.get("faces_binary") != nullptr || item.get("faces") != nullptr || mesh_session_submesh_for_item(item) != nullptr) {
            result.face_count = mesh_faces_from_item(item, result.vertex_count).size();
        }
        const std::size_t explicit_uv_count = static_cast<std::size_t>(std::max(0, int_or(item.get("uv_count"), 0)));
        const bool explicit_has_uvs = bool_or(item.get("has_uvs"), false);
        if (item.get("uvs_binary") != nullptr || item.get("uvs") != nullptr || mesh_session_submesh_for_item(item) != nullptr) {
            result.has_uvs = mesh_uvs_from_item(item).size() == result.vertex_count && result.vertex_count > 0;
        } else {
            result.has_uvs = explicit_has_uvs || explicit_uv_count > 0;
        }
        if (!vertices.empty()) {
            result.has_bounds = true;
            result.bbox_min = vertices.front();
            result.bbox_max = vertices.front();
            for (const Vec3& vertex : vertices) {
                result.bbox_min[0] = std::min(result.bbox_min[0], vertex[0]);
                result.bbox_min[1] = std::min(result.bbox_min[1], vertex[1]);
                result.bbox_min[2] = std::min(result.bbox_min[2], vertex[2]);
                result.bbox_max[0] = std::max(result.bbox_max[0], vertex[0]);
                result.bbox_max[1] = std::max(result.bbox_max[1], vertex[1]);
                result.bbox_max[2] = std::max(result.bbox_max[2], vertex[2]);
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionBoundsResult> run_selection_bounds(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshSelectionBoundsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshSelectionBoundsResult result;
        result.index = int_or(item.get("index"), -1);
        if (result.index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        if (vertices.empty()) {
            results.push_back(std::move(result));
            continue;
        }
        const std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertices.size());
        for (const int vertex_index : selected_vertices) {
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
                continue;
            }
            const Vec3& vertex = vertices[static_cast<std::size_t>(vertex_index)];
            if (!result.has_bounds) {
                result.bbox_min = vertex;
                result.bbox_max = vertex;
                result.has_bounds = true;
            } else {
                result.bbox_min[0] = std::min(result.bbox_min[0], vertex[0]);
                result.bbox_min[1] = std::min(result.bbox_min[1], vertex[1]);
                result.bbox_min[2] = std::min(result.bbox_min[2], vertex[2]);
                result.bbox_max[0] = std::max(result.bbox_max[0], vertex[0]);
                result.bbox_max[1] = std::max(result.bbox_max[1], vertex[1]);
                result.bbox_max[2] = std::max(result.bbox_max[2], vertex[2]);
            }
            ++result.selected_vertex_count;
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionPreviewResult> run_selection_preview(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshSelectionPreviewResult> results;
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
        std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        if (item.get("source_face_indices_binary") == nullptr
            && item.get("source_face_indices") == nullptr
            && item.get("source_face_start") == nullptr
            && item.get("faces") != nullptr) {
            const std::vector<int> raw_source_faces = source_face_indices_from_faces_json(item.get("faces"), vertex_count);
            if (raw_source_faces.size() == faces.size()) {
                source_faces = raw_source_faces;
            }
        }
        std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
        const std::vector<int> selected_face_items = int_vector_from_binary_or_json(
            item,
            "selected_faces_binary",
            "selected_faces",
            "selected_face_start",
            "selected_face_count"
        );
        std::set<int> selected_faces;
        for (const int face_index : selected_face_items) {
            if (face_index >= 0) {
                selected_faces.insert(face_index);
            }
        }
        std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertex_count);
        if (!faces.empty() && !selected_edges.empty()) {
            const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
            std::set<std::array<int, 2>> kept_edges;
            for (const auto& edge : selected_edges) {
                if (existing_edges.find(edge) != existing_edges.end()) {
                    kept_edges.insert(edge);
                }
            }
            selected_edges = std::move(kept_edges);
        }
        if (bool_or(item.get("selected_all_vertices"), false)) {
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                selected_vertices.insert(static_cast<int>(vertex_index));
            }
        }
        for (const auto& edge : selected_edges) {
            selected_vertices.insert(edge[0]);
            selected_vertices.insert(edge[1]);
        }
        std::set<int> selected_source_faces;
        for (std::size_t face_offset = 0; face_offset < faces.size(); ++face_offset) {
            const int source_face_index = face_offset < source_faces.size()
                ? source_faces[face_offset]
                : static_cast<int>(face_offset);
            if (selected_faces.find(source_face_index) == selected_faces.end()) {
                continue;
            }
            selected_source_faces.insert(source_face_index);
            const auto& face = faces[face_offset];
            selected_vertices.insert(face[0]);
            selected_vertices.insert(face[1]);
            selected_vertices.insert(face[2]);
        }
        if (selected_vertices.empty()) {
            continue;
        }
        SubmeshSelectionPreviewResult result;
        result.index = submesh_index;
        result.source_vertex_indices.assign(selected_vertices.begin(), selected_vertices.end());
        result.source_face_indices.assign(selected_source_faces.begin(), selected_source_faces.end());
        result.source_edges.assign(selected_edges.begin(), selected_edges.end());
        result.selection_preview_path = string_or(item.get("selection_preview_output_path"), "");
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionPruneResult> run_selection_prune(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string root_selection_operation = normalized_selection_operation(
        string_or(root.get("selection_operation"), "replace")
    );
    std::vector<SubmeshSelectionPruneResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const std::string selection_operation = normalized_selection_operation(
            string_or(item.get("selection_operation"), root_selection_operation)
        );
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        if (submesh_index < 0 || vertex_count == 0) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        if (item.get("source_face_indices_binary") == nullptr
            && item.get("source_face_indices") == nullptr
            && item.get("source_face_start") == nullptr
            && item.get("faces") != nullptr) {
            const std::vector<int> raw_source_faces = source_face_indices_from_faces_json(item.get("faces"), vertex_count);
            if (raw_source_faces.size() == faces.size()) {
                source_faces = raw_source_faces;
            }
        }

        std::set<int> selected_vertices = combine_selection_sets(
            selected_vertices_from_binary_or_json_keys(
                item,
                vertex_count,
                "current_selected_vertices_binary",
                "current_selected_vertices",
                "current_selected_vertex_start",
                "current_selected_vertex_count"
            ),
            selected_vertices_from_binary_or_json(item, vertex_count),
            selection_operation
        );

        std::set<std::array<int, 2>> selected_edges = combine_selection_sets(
            selected_edges_from_binary_or_json_keys(
                item,
                vertex_count,
                "current_selected_edges_binary",
                "current_selected_edges"
            ),
            selected_edges_from_binary_or_json(item, vertex_count),
            selection_operation
        );
        if (!faces.empty() && !selected_edges.empty()) {
            const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
            std::set<std::array<int, 2>> kept_edges;
            for (const auto& edge : selected_edges) {
                if (existing_edges.find(edge) != existing_edges.end()) {
                    kept_edges.insert(edge);
                }
            }
            selected_edges = std::move(kept_edges);
        }

        const int explicit_face_count = int_or(item.get("face_count"), static_cast<int>(faces.size()));
        const std::size_t selection_face_count = explicit_face_count > 0
            ? static_cast<std::size_t>(explicit_face_count)
            : faces.size();
        std::set<int> selected_faces = combine_selection_sets(
            selected_prune_faces_from_keys(
                item,
                "current_selected_faces_binary",
                "current_selected_faces",
                selection_face_count,
                faces,
                source_faces
            ),
            selected_prune_faces_from_keys(
                item,
                "selected_faces_binary",
                "selected_faces",
                selection_face_count,
                faces,
                source_faces
            ),
            selection_operation
        );

        if (selected_vertices.empty() && selected_edges.empty() && selected_faces.empty()) {
            continue;
        }
        SubmeshSelectionPruneResult result;
        result.index = submesh_index;
        result.selected_vertices.assign(selected_vertices.begin(), selected_vertices.end());
        result.selected_edges.assign(selected_edges.begin(), selected_edges.end());
        result.selected_faces.assign(selected_faces.begin(), selected_faces.end());
        result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "");
        result.selected_edges_path = string_or(item.get("selected_edges_output_path"), "");
        result.selected_faces_path = string_or(item.get("selected_faces_output_path"), "");
        results.push_back(std::move(result));
    }
    return results;
}

double brush_falloff_weight(double distance, double radius, const std::string& falloff) {
    if (radius <= 1e-8) {
        return distance <= 1e-8 ? 1.0 : 0.0;
    }
    const double normalized = std::max(0.0, std::min(1.0, distance / radius));
    if (normalized >= 1.0) {
        return 0.0;
    }
    if (falloff == "linear") {
        return 1.0 - normalized;
    }
    if (falloff == "sharp") {
        return (1.0 - normalized) * (1.0 - normalized);
    }
    if (falloff == "constant") {
        return 1.0;
    }
    const double t = normalized;
    return 1.0 - (t * t * (3.0 - 2.0 * t));
}
