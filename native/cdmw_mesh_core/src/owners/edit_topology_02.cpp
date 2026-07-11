std::map<int, int> build_x_mirror_pairs_native(const std::vector<Vec3>& vertices) {
    std::map<std::array<long long, 3>, std::vector<int>> buckets;
    const double scale = 10000.0;
    for (std::size_t i = 0; i < vertices.size(); ++i) {
        const Vec3& vertex = vertices[i];
        const std::array<long long, 3> key{
            static_cast<long long>(std::llround(vertex[0] * scale)),
            static_cast<long long>(std::llround(vertex[1] * scale)),
            static_cast<long long>(std::llround(vertex[2] * scale)),
        };
        buckets[key].push_back(static_cast<int>(i));
    }
    std::map<int, int> pairs;
    for (std::size_t i = 0; i < vertices.size(); ++i) {
        const Vec3& vertex = vertices[i];
        const std::array<long long, 3> mirror_key{
            static_cast<long long>(std::llround(-vertex[0] * scale)),
            static_cast<long long>(std::llround(vertex[1] * scale)),
            static_cast<long long>(std::llround(vertex[2] * scale)),
        };
        const auto found = buckets.find(mirror_key);
        if (found == buckets.end() || found->second.empty()) {
            continue;
        }
        const Vec3 expected{-vertex[0], vertex[1], vertex[2]};
        int best = found->second.front();
        double best_distance = distance_squared_vec3(vertices[static_cast<std::size_t>(best)], expected);
        for (const int candidate : found->second) {
            const double distance = distance_squared_vec3(vertices[static_cast<std::size_t>(candidate)], expected);
            if (distance < best_distance) {
                best = candidate;
                best_distance = distance;
            }
        }
        pairs[static_cast<int>(i)] = best;
    }
    return pairs;
}

std::map<int, double> vertex_weights_from_json(
    const JsonValue* value,
    std::size_t vertex_count,
    const std::set<int>* allowed
) {
    std::map<int, double> weights;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return weights;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        const int index = int_or(&item.array_value[0], -1);
        const double weight = std::max(0.0, std::min(1.0, number_or(&item.array_value[1], 0.0)));
        if (index < 0 || static_cast<std::size_t>(index) >= vertex_count || weight <= 0.0) {
            continue;
        }
        if (allowed != nullptr && allowed->find(index) == allowed->end()) {
            continue;
        }
        weights[index] = std::max(weights[index], weight);
    }
    return weights;
}

std::map<int, double> vertex_weights_from_edit(
    const JsonValue& edit,
    std::size_t vertex_count,
    const std::set<int>* allowed
) {
    std::map<int, double> weights;
    const JsonValue* binary_indices = edit.get("vertex_weight_indices_binary");
    const JsonValue* binary_weights = edit.get("vertex_weights_binary");
    if (binary_indices != nullptr || binary_weights != nullptr) {
        if (binary_indices == nullptr || binary_weights == nullptr) {
            return weights;
        }
        const std::vector<int> indices = int_vector_from_binary(binary_indices);
        const std::vector<double> values = double_vector_from_f32_or_f64_binary(binary_weights);
        if (indices.size() != values.size()) {
            return weights;
        }
        for (std::size_t offset = 0; offset < indices.size(); ++offset) {
            const int index = indices[offset];
            const double weight = std::max(0.0, std::min(1.0, values[offset]));
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count || weight <= 0.0) {
                continue;
            }
            if (allowed != nullptr && allowed->find(index) == allowed->end()) {
                continue;
            }
            weights[index] = std::max(weights[index], weight);
        }
        return weights;
    }
    return vertex_weights_from_json(edit.get("vertex_weights"), vertex_count, allowed);
}

std::map<int, double> affected_vertex_weights_native(
    const JsonValue& item,
    const std::vector<Vec3>& vertices,
    const Vec3& center,
    double radius,
    const std::string& falloff,
    const std::set<int>* allowed,
    const JsonValue& edit
) {
    const bool has_explicit_weights = edit.get("vertex_weights") != nullptr
        || edit.get("vertex_weight_indices_binary") != nullptr
        || edit.get("vertex_weights_binary") != nullptr;
    std::map<int, double> weights = vertex_weights_from_edit(edit, vertices.size(), allowed);
    if (!weights.empty() || has_explicit_weights) {
        return weights;
    }
    const JsonValue* raw_screen_brush = edit.get("screen_brush");
    MeshEditorScreenBrushDepthMask depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* depth_mask = mesh_editor_screen_brush_depth_mask_for_edit(
        item,
        edit,
        raw_screen_brush,
        depth_mask_storage
    );
    const std::string stroke_phase = lower_ascii(string_or(edit.get("stroke_phase"), ""));
    const std::string target_mode = lower_ascii(string_or(edit.get("target_mode"), ""));
    const bool prefer_screen_brush = raw_screen_brush != nullptr
        && (stroke_phase == "update" || stroke_phase == "end" || target_mode != "selection");
    const bool screen_brush_projection_payload = mesh_editor_has_projection_payload(
        raw_screen_brush,
        int_or(item.get("index"), -1)
    );
    if (prefer_screen_brush) {
        weights = screen_brush_vertex_weights_native(item, vertices, allowed, falloff, raw_screen_brush, depth_mask);
        if (!weights.empty() || screen_brush_projection_payload) {
            return weights;
        }
        if (mesh_editor_screen_brush_projection_unresolved_for_item(item, raw_screen_brush)) {
            return weights;
        }
    }
    bool has_selection_weights = false;
    weights = selected_vertex_weights_from_editor_session(item, vertices.size(), allowed, has_selection_weights);
    if (!weights.empty() || has_selection_weights) {
        return weights;
    }
    weights = screen_brush_vertex_weights_native(item, vertices, allowed, falloff, raw_screen_brush, depth_mask);
    if (!weights.empty() || screen_brush_projection_payload) {
        return weights;
    }
    if (mesh_editor_screen_brush_projection_unresolved_for_item(item, raw_screen_brush)) {
        return weights;
    }
    if (allowed != nullptr) {
        for (const int index : *allowed) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
                continue;
            }
            double weight = brush_falloff_weight(length_vec3(sub_vec3(vertices[static_cast<std::size_t>(index)], center)), radius, falloff);
            if (radius <= 1e-8) {
                weight = 1.0;
            }
            if (weight > 0.0 || allowed->find(index) != allowed->end()) {
                weights[index] = std::max(weight, weights[index]);
            }
        }
        return weights;
    }
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        const double weight = brush_falloff_weight(length_vec3(sub_vec3(vertices[index], center)), radius, falloff);
        if (weight > 0.0) {
            weights[static_cast<int>(index)] = weight;
        }
    }
    return weights;
}

std::map<int, std::pair<double, bool>> with_mirror_weights_native(
    const std::vector<Vec3>& vertices,
    const std::map<int, double>& weights,
    bool mirror_x,
    std::map<int, int> mirror_pairs
) {
    std::map<int, std::pair<double, bool>> result;
    for (const auto& item : weights) {
        if (item.first >= 0 && static_cast<std::size_t>(item.first) < vertices.size() && item.second > 0.0) {
            result[item.first] = {item.second, false};
        }
    }
    if (!mirror_x) {
        return result;
    }
    if (mirror_pairs.empty()) {
        mirror_pairs = build_x_mirror_pairs_native(vertices);
    }
    for (const auto& item : result) {
        const auto found = mirror_pairs.find(item.first);
        if (found == mirror_pairs.end()) {
            continue;
        }
        const int mirror_index = found->second;
        const auto existing = result.find(mirror_index);
        if (existing == result.end() || item.second.first > existing->second.first) {
            result[mirror_index] = {item.second.first, true};
        }
    }
    return result;
}

Vec3 brush_weighted_center(
    const std::vector<Vec3>& vertices,
    const std::map<int, double>& weights,
    const Vec3& fallback
) {
    Vec3 sum{0.0, 0.0, 0.0};
    double total_weight = 0.0;
    for (const auto& item : weights) {
        if (item.first < 0 || static_cast<std::size_t>(item.first) >= vertices.size()) continue;
        const double weight = std::max(0.0, std::min(1.0, item.second));
        if (weight <= 0.0) continue;
        sum = add_vec3(sum, scale_vec3(vertices[static_cast<std::size_t>(item.first)], weight));
        total_weight += weight;
    }
    return total_weight > 1e-8 ? scale_vec3(sum, 1.0 / total_weight) : fallback;
}

std::vector<Vec3> smooth_brush_vertices(
    const std::vector<Vec3>& original,
    const std::vector<std::array<int, 3>>& faces,
    const std::map<int, std::pair<double, bool>>& weighted,
    int iterations,
    double strength
) {
    std::vector<Vec3> relaxed = original;
    const std::vector<std::set<int>> adjacency = build_vertex_adjacency(original.size(), faces);
    for (int iteration = 0; iteration < iterations; ++iteration) {
        std::vector<Vec3> next = relaxed;
        for (const auto& item : weighted) {
            const int index = item.first;
            if (index < 0 || static_cast<std::size_t>(index) >= adjacency.size()) continue;
            const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(index)];
            if (neighbors.empty()) continue;
            Vec3 sum{0.0, 0.0, 0.0};
            int count = 0;
            for (const int neighbor : neighbors) {
                if (neighbor < 0 || static_cast<std::size_t>(neighbor) >= relaxed.size()) continue;
                sum = add_vec3(sum, relaxed[static_cast<std::size_t>(neighbor)]);
                ++count;
            }
            if (count <= 0) continue;
            const Vec3 vertex = relaxed[static_cast<std::size_t>(index)];
            const Vec3 average = scale_vec3(sum, 1.0 / static_cast<double>(count));
            const double blend = std::max(0.0, std::min(1.0, item.second.first * strength));
            next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(sub_vec3(average, vertex), blend));
        }
        relaxed = std::move(next);
    }
    return relaxed;
}

SubmeshMeshEditResult run_brush_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "brush";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        return result;
    }

    const std::string tool = string_or(edit.get("tool"), "grab");
    const JsonValue* screen_radius_payload = edit.get("screen_radius");
    const bool screen_radius_projection_payload = mesh_editor_has_projection_payload(screen_radius_payload, result.index);
    const bool has_center = edit.get("center") != nullptr && !screen_radius_projection_payload;
    Vec3 center = has_center ? vec3_or(edit.get("center"), {0.0, 0.0, 0.0}) : Vec3{0.0, 0.0, 0.0};
    const double initial_screen_radius = screen_radius_projection_payload
        ? 0.0
        : (has_center
            ? mesh_editor_screen_radius_units_at_center(screen_radius_payload, center, result.index)
            : mesh_editor_screen_radius_units(screen_radius_payload));
    double radius = std::max(
        screen_radius_projection_payload
            ? 1.0
            : number_or(edit.get("radius"), initial_screen_radius > 0.0 ? initial_screen_radius : 1.0),
        1e-8
    );
    const double strength = std::max(0.0, std::min(1.0, number_or(edit.get("strength"), 1.0)));
    std::string falloff = string_or(edit.get("falloff"), "smooth");
    std::transform(falloff.begin(), falloff.end(), falloff.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const bool mirror_x = bool_or(edit.get("mirror_x"), false);
    const bool invert = bool_or(edit.get("invert"), false);
    const bool sparse_output = bool_or(item.get("sparse_output"), bool_or(edit.get("sparse_output"), false));
    const int iterations = std::max(1, std::min(12, int_or(edit.get("iterations"), 1)));

    std::set<int> selected = selected_vertices_from_edit_domains(item, result.vertices.size(), faces);
    const bool restrict_selection = bool_or(item.get("selection_restricts_vertices"), false);
    const std::set<int>* allowed = restrict_selection ? &selected : nullptr;
    const std::map<int, double> direct_weights = affected_vertex_weights_native(
        item,
        result.vertices,
        center,
        radius,
        falloff,
        allowed,
        edit
    );
    if (!has_center && !direct_weights.empty()) center = brush_weighted_center(result.vertices, direct_weights, center);
    const double screen_radius = mesh_editor_screen_radius_units_at_center(screen_radius_payload, center, result.index);
    if (screen_radius_projection_payload) {
        if (screen_radius <= 0.0) {
            result.vertices.clear();
            return result;
        }
        radius = std::max(screen_radius, 1e-8);
    }
    const JsonValue* screen_drag_payload = edit.get("screen_drag");
    const bool screen_drag_projection_payload = mesh_editor_has_projection_payload(screen_drag_payload, result.index);
    const Vec3 drag_base = screen_drag_projection_payload
        ? Vec3{0.0, 0.0, 0.0}
        : vec3_or(edit.get("drag_delta"), vec3_or(edit.get("delta"), {0.0, 0.0, 0.0}));
    const Vec3 drag_delta = add_screen_drag_delta(
        drag_base,
        screen_drag_payload,
        &center,
        result.index
    );
    double amount = screen_radius_projection_payload ? 0.0 : number_or(edit.get("amount"), 0.0);
    if (std::abs(amount) <= 1e-8) {
        if ((tool == "inflate" || tool == "pinch") && screen_radius > 1e-8) {
            const double amount_scale = number_or(screen_radius_payload->get("amount_scale"), 0.08);
            amount = screen_radius * amount_scale;
        } else {
            amount = length_vec3(drag_delta);
        }
    }
    amount *= strength;
    const std::map<int, std::pair<double, bool>> weighted = with_mirror_weights_native(
        result.vertices,
        direct_weights,
        mirror_x,
        mirror_pairs_from_json(item.get("mirror_pairs"), result.vertices.size())
    );
    if (weighted.empty()) {
        result.vertices.clear();
        return result;
    }

    const std::vector<Vec3> original = result.vertices;
    std::vector<Vec3> next = original;
    if (tool == "smooth") {
        next = smooth_brush_vertices(original, faces, weighted, iterations, strength);
    } else {
        std::vector<Vec3> normals = vertices_from_binary_or_json(item, "normals_binary", "normals");
        if (tool == "inflate" && normals.size() != original.size()) {
            normals = compute_smooth_normals(original, faces);
        }
        for (const auto& item_weight : weighted) {
            const int index = item_weight.first;
            if (index < 0 || static_cast<std::size_t>(index) >= original.size()) {
                continue;
            }
            const double weight = item_weight.second.first;
            const bool mirrored = item_weight.second.second;
            const Vec3 vertex = original[static_cast<std::size_t>(index)];
            const Vec3 applied_delta = mirrored ? Vec3{-drag_delta[0], drag_delta[1], drag_delta[2]} : drag_delta;
            if (tool == "grab") {
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(applied_delta, weight * strength));
            } else if (tool == "inflate") {
                const Vec3 fallback = normalized_vec3(sub_vec3(vertex, center), {0.0, 1.0, 0.0});
                const Vec3 normal = normalized_vec3(normals[static_cast<std::size_t>(index)], fallback);
                const double signed_amount = invert ? -amount : amount;
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(normal, signed_amount * weight));
            } else if (tool == "pinch") {
                const Vec3 local_center = mirrored ? Vec3{-center[0], center[1], center[2]} : center;
                const Vec3 direction = normalized_vec3(sub_vec3(local_center, vertex), {0.0, 0.0, 0.0});
                const double signed_amount = invert ? -std::abs(amount) : std::abs(amount);
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(direction, signed_amount * weight));
            } else {
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(applied_delta, weight * strength));
            }
        }
    }

    for (const auto& item_weight : weighted) {
        const int index = item_weight.first;
        if (index >= 0
            && static_cast<std::size_t>(index) < original.size()
            && !same_vec3(original[static_cast<std::size_t>(index)], next[static_cast<std::size_t>(index)])) {
            result.changed_vertices.push_back(index);
        }
    }
    if (result.changed_vertices.empty()) {
        result.vertices.clear();
        return result;
    }
    result.vertices = std::move(next);
    if (sparse_output) {
        result.sparse = true;
        result.changed_positions.reserve(result.changed_vertices.size());
        result.before_positions.reserve(result.changed_vertices.size());
        for (const int index : result.changed_vertices) {
            if (index >= 0 && static_cast<std::size_t>(index) < result.vertices.size()) {
                result.changed_positions.push_back(result.vertices[static_cast<std::size_t>(index)]);
                result.before_positions.push_back(original[static_cast<std::size_t>(index)]);
            }
        }
    }
    return result;
}

SubmeshMeshEditResult run_delete_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "delete";
    result.index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    if (result.index < 0 || vertices.empty() || faces.empty()) {
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
    if (selected_faces.empty()) {
        return result;
    }
    const bool remove_orphans = bool_or(edit.get("remove_orphans"), true);
    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        kept_faces.push_back(faces[face_index]);
        kept_source_faces.push_back(
            face_index < source_faces.size()
                ? source_faces[face_index]
                : static_cast<int>(face_index)
        );
    }
    if (result.removed_faces <= 0) {
        return result;
    }
    if (!remove_orphans) {
        result.vertices = vertices;
        result.faces = std::move(kept_faces);
        result.source_face_indices = std::move(kept_source_faces);
        result.copy_vertex_indices.resize(vertices.size());
        result.index_map.resize(vertices.size());
        for (std::size_t i = 0; i < vertices.size(); ++i) {
            result.copy_vertex_indices[i] = static_cast<int>(i);
            result.index_map[i] = static_cast<int>(i);
        }
        result.topology_changed = true;
        return result;
    }
    std::set<int> used_vertices;
    for (const auto& face : kept_faces) {
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    std::map<int, int> index_map;
    for (const int old_index : used_vertices) {
        index_map[old_index] = static_cast<int>(result.vertices.size());
        result.vertices.push_back(vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }
    for (std::size_t kept_index = 0; kept_index < kept_faces.size(); ++kept_index) {
        const auto& face = kept_faces[kept_index];
        const auto a = index_map.find(face[0]);
        const auto b = index_map.find(face[1]);
        const auto c = index_map.find(face[2]);
        if (a != index_map.end() && b != index_map.end() && c != index_map.end()) {
            result.faces.push_back({a->second, b->second, c->second});
            result.source_face_indices.push_back(
                kept_index < kept_source_faces.size()
                    ? kept_source_faces[kept_index]
                    : static_cast<int>(kept_index)
            );
        }
    }
    result.index_map.assign(vertices.size(), -1);
    for (const auto& item_map : index_map) {
        result.index_map[static_cast<std::size_t>(item_map.first)] = item_map.second;
    }
    result.removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(result.vertices.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_dissolve_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "dissolve";
    result.index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    if (result.index < 0 || vertices.empty() || faces.empty()) {
        return result;
    }
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() != faces.size()) {
        source_faces = identity_indices(faces.size());
    }

    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertices.size());
    if (!selected_edges.empty()) {
        std::map<std::array<int, 2>, std::vector<int>> edge_faces;
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            const auto& face = faces[face_index];
            edge_faces[edge_key(face[0], face[1])].push_back(static_cast<int>(face_index));
            edge_faces[edge_key(face[1], face[2])].push_back(static_cast<int>(face_index));
            edge_faces[edge_key(face[2], face[0])].push_back(static_cast<int>(face_index));
        }

        bool internal_edges = true;
        for (const auto& edge : selected_edges) {
            if (edge_faces[edge].size() != 2) {
                internal_edges = false;
                break;
            }
        }

        std::map<int, std::array<int, 3>> replacements;
        std::set<int> used_faces;
        if (internal_edges) {
            for (const auto& edge : selected_edges) {
                const std::vector<int>& face_indices = edge_faces[edge];
                if (used_faces.find(face_indices[0]) != used_faces.end()
                    || used_faces.find(face_indices[1]) != used_faces.end()) {
                    replacements.clear();
                    internal_edges = false;
                    break;
                }
                const int left = edge[0];
                const int right = edge[1];
                const std::array<int, 3>& first_face = faces[static_cast<std::size_t>(face_indices[0])];
                const std::array<int, 3>& second_face = faces[static_cast<std::size_t>(face_indices[1])];
                int first_opposite = -1;
                int second_opposite = -1;
                for (const int index : first_face) {
                    if (index != left && index != right) {
                        first_opposite = index;
                        break;
                    }
                }
                for (const int index : second_face) {
                    if (index != left && index != right) {
                        second_opposite = index;
                        break;
                    }
                }
                if (first_opposite < 0 || second_opposite < 0 || first_opposite == second_opposite) {
                    replacements.clear();
                    internal_edges = false;
                    break;
                }
                const int lower = std::min(face_indices[0], face_indices[1]);
                const int upper = std::max(face_indices[0], face_indices[1]);
                replacements[lower] = {first_opposite, left, second_opposite};
                replacements[upper] = {first_opposite, second_opposite, right};
                used_faces.insert(face_indices[0]);
                used_faces.insert(face_indices[1]);
            }
        }

        if (internal_edges && !replacements.empty()) {
            result.vertices = vertices;
            result.faces.reserve(faces.size());
            result.source_face_indices.reserve(faces.size());
            for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
                const auto found = replacements.find(static_cast<int>(face_index));
                result.faces.push_back(found != replacements.end() ? found->second : faces[face_index]);
                result.source_face_indices.push_back(source_faces[face_index]);
            }
            result.copy_vertex_indices = identity_indices(result.vertices.size());
            result.index_map = identity_indices(result.vertices.size());
            result.topology_changed = true;
            return result;
        }
    }

    const std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
    if (selected_faces.empty()) {
        return result;
    }
    result.vertices = vertices;
    result.faces.reserve(faces.size());
    result.source_face_indices.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        result.faces.push_back(faces[face_index]);
        result.source_face_indices.push_back(source_faces[face_index]);
    }
    if (result.removed_faces <= 0) {
        result.vertices.clear();
        result.faces.clear();
        result.source_face_indices.clear();
        return result;
    }
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.index_map = identity_indices(result.vertices.size());
    result.topology_changed = true;
    return result;
}
