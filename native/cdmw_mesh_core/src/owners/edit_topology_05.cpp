SubmeshMeshEditResult run_fill_holes_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "fill_holes";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::map<std::array<int, 2>, int> edge_use_count;
    for (const auto& face : original_faces) {
        ++edge_use_count[edge_key(face[0], face[1])];
        ++edge_use_count[edge_key(face[1], face[2])];
        ++edge_use_count[edge_key(face[2], face[0])];
    }
    std::set<std::array<int, 2>> pending_edges;
    for (const auto& item_count : edge_use_count) {
        if (item_count.second == 1) {
            pending_edges.insert(item_count.first);
        }
    }
    if (pending_edges.empty()) {
        result.vertices.clear();
        return result;
    }

    auto sorted_face_key = [](std::array<int, 3> face) {
        std::sort(face.begin(), face.end());
        return face;
    };
    std::set<std::array<int, 3>> existing_faces;
    for (const auto& face : original_faces) {
        existing_faces.insert(sorted_face_key(face));
    }

    std::vector<std::array<int, 3>> added_faces;
    while (!pending_edges.empty()) {
        std::set<std::array<int, 2>> component;
        std::set<int> component_vertices;
        const std::array<int, 2> seed = *pending_edges.begin();
        pending_edges.erase(pending_edges.begin());
        component.insert(seed);
        component_vertices.insert(seed[0]);
        component_vertices.insert(seed[1]);
        bool changed = true;
        while (changed) {
            changed = false;
            for (auto edge_it = pending_edges.begin(); edge_it != pending_edges.end();) {
                const std::array<int, 2> edge = *edge_it;
                if (component_vertices.find(edge[0]) != component_vertices.end()
                    || component_vertices.find(edge[1]) != component_vertices.end()) {
                    component.insert(edge);
                    component_vertices.insert(edge[0]);
                    component_vertices.insert(edge[1]);
                    edge_it = pending_edges.erase(edge_it);
                    changed = true;
                } else {
                    ++edge_it;
                }
            }
        }

        const std::vector<int> order = closed_edge_loop_order(component);
        if (order.size() == 3) {
            const std::array<int, 3> face{order[0], order[1], order[2]};
            const std::array<int, 3> key = sorted_face_key(face);
            if (existing_faces.find(key) == existing_faces.end()) {
                added_faces.push_back(face);
                existing_faces.insert(key);
            }
        } else if (order.size() == 4) {
            const std::array<int, 3> first{order[0], order[1], order[2]};
            const std::array<int, 3> second{order[0], order[2], order[3]};
            for (const auto& face : {first, second}) {
                const std::array<int, 3> key = sorted_face_key(face);
                if (existing_faces.find(key) == existing_faces.end()) {
                    added_faces.push_back(face);
                    existing_faces.insert(key);
                }
            }
        }
    }
    if (added_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    result.faces = original_faces;
    result.faces.insert(result.faces.end(), added_faces.begin(), added_faces.end());
    result.source_face_indices = mesh_source_face_indices_from_item(item, original_faces.size());
    if (result.source_face_indices.size() != original_faces.size()) {
        result.source_face_indices = identity_indices(original_faces.size());
    }
    int next_generated_source_face = static_cast<int>(result.source_face_indices.size());
    for (const int source_face_index : result.source_face_indices) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    for (std::size_t added_index = 0; added_index < added_faces.size(); ++added_index) {
        result.source_face_indices.push_back(next_generated_source_face + static_cast<int>(added_index));
    }
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.added_faces = static_cast<int>(added_faces.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_fill_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "fill";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, result.vertices.size());
    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    std::vector<int> edge_loop;
    if (!selected_edges.empty()) {
        for (const auto& edge : selected_edges) {
            selected_vertices.insert(edge[0]);
            selected_vertices.insert(edge[1]);
        }
        edge_loop = closed_edge_loop_order(selected_edges);
    }
    if (selected_vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<int> indices;
    bool use_edge_loop = !edge_loop.empty() && edge_loop.size() == selected_vertices.size();
    if (use_edge_loop) {
        for (const int index : edge_loop) {
            if (selected_vertices.find(index) == selected_vertices.end()) {
                use_edge_loop = false;
                break;
            }
        }
    }
    if (use_edge_loop) {
        indices = std::move(edge_loop);
    } else {
        indices.assign(selected_vertices.begin(), selected_vertices.end());
    }
    if (indices.size() != 3 && indices.size() != 4) {
        result.vertices.clear();
        return result;
    }

    auto sorted_face_key = [](std::array<int, 3> face) {
        std::sort(face.begin(), face.end());
        return face;
    };
    std::set<std::array<int, 3>> existing_faces;
    for (const auto& face : original_faces) {
        existing_faces.insert(sorted_face_key(face));
    }

    std::vector<std::array<int, 3>> faces_to_add;
    const std::set<int> selected_set(indices.begin(), indices.end());
    if (indices.size() == 3) {
        const std::array<int, 3> face{indices[0], indices[1], indices[2]};
        if (existing_faces.find(sorted_face_key(face)) == existing_faces.end()) {
            faces_to_add.push_back(face);
        }
    } else {
        int inside_count = 0;
        std::set<int> covered_vertices;
        for (const auto& face : existing_faces) {
            if (selected_set.find(face[0]) == selected_set.end()
                || selected_set.find(face[1]) == selected_set.end()
                || selected_set.find(face[2]) == selected_set.end()) {
                continue;
            }
            ++inside_count;
            covered_vertices.insert(face[0]);
            covered_vertices.insert(face[1]);
            covered_vertices.insert(face[2]);
        }
        if (inside_count >= 2 && covered_vertices == selected_set) {
            result.vertices.clear();
            return result;
        }
        const std::array<int, 3> first{indices[0], indices[1], indices[2]};
        const std::array<int, 3> second{indices[0], indices[2], indices[3]};
        for (const auto& face : {first, second}) {
            if (existing_faces.find(sorted_face_key(face)) == existing_faces.end()) {
                faces_to_add.push_back(face);
            }
        }
    }
    if (faces_to_add.empty()) {
        result.vertices.clear();
        return result;
    }

    result.faces = original_faces;
    result.faces.insert(result.faces.end(), faces_to_add.begin(), faces_to_add.end());
    result.source_face_indices = mesh_source_face_indices_from_item(item, original_faces.size());
    if (result.source_face_indices.size() != original_faces.size()) {
        result.source_face_indices = identity_indices(original_faces.size());
    }
    int next_generated_source_face = static_cast<int>(result.source_face_indices.size());
    for (const int source_face_index : result.source_face_indices) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    for (std::size_t added_index = 0; added_index < faces_to_add.size(); ++added_index) {
        result.source_face_indices.push_back(next_generated_source_face + static_cast<int>(added_index));
    }
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.added_faces = static_cast<int>(faces_to_add.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_triangulate_display_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "triangulate_display";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<DisplayFace> display_faces = display_faces_from_json(item.get("display_faces"), result.vertices.size());
    if (display_faces.empty() && item.get("display_faces") == nullptr) {
        const std::vector<std::array<int, 3>> current_faces = mesh_faces_from_item(item, result.vertices.size());
        display_faces.reserve(current_faces.size());
        for (std::size_t face_index = 0; face_index < current_faces.size(); ++face_index) {
            const auto& current = current_faces[face_index];
            DisplayFace face;
            face.indices = {current[0], current[1], current[2]};
            face.source_index = static_cast<int>(face_index);
            face.valid = true;
            display_faces.push_back(std::move(face));
        }
    }
    if (display_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<std::array<int, 3>> triangulated_faces;
    std::vector<int> triangulated_source_faces;
    for (const DisplayFace& face : display_faces) {
        if (!face.valid || face.indices.size() < 3) {
            continue;
        }
        if (face.indices.size() == 3) {
            const std::array<int, 3> triangle{face.indices[0], face.indices[1], face.indices[2]};
            if (triangle[0] != triangle[1] && triangle[0] != triangle[2] && triangle[1] != triangle[2]) {
                triangulated_faces.push_back(triangle);
                triangulated_source_faces.push_back(face.source_index);
            }
            continue;
        }
        for (std::size_t offset = 1; offset + 1 < face.indices.size(); ++offset) {
            const std::array<int, 3> triangle{
                face.indices[0],
                face.indices[offset],
                face.indices[offset + 1],
            };
            if (triangle[0] != triangle[1] && triangle[0] != triangle[2] && triangle[1] != triangle[2]) {
                triangulated_faces.push_back(triangle);
                triangulated_source_faces.push_back(face.source_index);
            }
        }
    }

    bool unchanged = display_faces.size() == triangulated_faces.size();
    if (unchanged) {
        for (std::size_t face_index = 0; face_index < display_faces.size(); ++face_index) {
            const DisplayFace& face = display_faces[face_index];
            const std::array<int, 3>& triangle = triangulated_faces[face_index];
            if (!face.valid
                || face.indices.size() != 3
                || face.indices[0] != triangle[0]
                || face.indices[1] != triangle[1]
                || face.indices[2] != triangle[2]) {
                unchanged = false;
                break;
            }
        }
    }
    if (unchanged) {
        result.vertices.clear();
        return result;
    }

    result.faces = std::move(triangulated_faces);
    result.source_face_indices = std::move(triangulated_source_faces);
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.removed_faces = std::max(0, static_cast<int>(display_faces.size()) - static_cast<int>(result.faces.size()));
    result.added_faces = std::max(0, static_cast<int>(result.faces.size()) - static_cast<int>(display_faces.size()));
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_bridge_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "bridge";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::set<std::array<int, 2>> selected_edge_set = selected_edges_from_binary_or_json(item, result.vertices.size());
    if (selected_edge_set.size() != 2) {
        result.vertices.clear();
        return result;
    }
    const std::vector<std::array<int, 2>> selected_edges(selected_edge_set.begin(), selected_edge_set.end());
    const int a = selected_edges[0][0];
    const int b = selected_edges[0][1];
    const int c = selected_edges[1][0];
    const int d = selected_edges[1][1];
    const std::set<int> selected_vertices{a, b, c, d};
    if (selected_vertices.size() != 4) {
        result.vertices.clear();
        return result;
    }

    auto sorted_face_key = [](std::array<int, 3> face) {
        std::sort(face.begin(), face.end());
        return face;
    };
    std::map<std::array<int, 2>, int> edge_use_count;
    std::set<std::array<int, 3>> existing_faces;
    bool existing_inside_selected_vertices = false;
    for (const auto& face : original_faces) {
        existing_faces.insert(sorted_face_key(face));
        ++edge_use_count[edge_key(face[0], face[1])];
        ++edge_use_count[edge_key(face[1], face[2])];
        ++edge_use_count[edge_key(face[2], face[0])];
        if (selected_vertices.find(face[0]) != selected_vertices.end()
            && selected_vertices.find(face[1]) != selected_vertices.end()
            && selected_vertices.find(face[2]) != selected_vertices.end()) {
            existing_inside_selected_vertices = true;
        }
    }
    if (edge_use_count[edge_key(a, b)] > 1 || edge_use_count[edge_key(c, d)] > 1 || existing_inside_selected_vertices) {
        result.vertices.clear();
        return result;
    }

    const std::array<int, 3> first{a, b, d};
    const std::array<int, 3> second{a, d, c};
    if (existing_faces.find(sorted_face_key(first)) != existing_faces.end()
        || existing_faces.find(sorted_face_key(second)) != existing_faces.end()) {
        result.vertices.clear();
        return result;
    }

    result.faces = original_faces;
    result.faces.push_back(first);
    result.faces.push_back(second);
    result.source_face_indices = mesh_source_face_indices_from_item(item, original_faces.size());
    if (result.source_face_indices.size() != original_faces.size()) {
        result.source_face_indices = identity_indices(original_faces.size());
    }
    int next_generated_source_face = static_cast<int>(result.source_face_indices.size());
    for (const int source_face_index : result.source_face_indices) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    result.source_face_indices.push_back(next_generated_source_face);
    result.source_face_indices.push_back(next_generated_source_face + 1);
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.added_faces = 2;
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_subdivide_edit_for_submesh(const JsonValue& item, const JsonValue& edit, bool refine) {
    SubmeshMeshEditResult result;
    result.action = refine ? "refine_smooth" : "subdivide";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    std::set<int> split_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    const int face_limit = std::max(1, int_or(edit.get("max_faces_per_submesh"), 256));
    while (static_cast<int>(split_faces.size()) > face_limit) {
        auto last = split_faces.end();
        --last;
        split_faces.erase(last);
    }
    if (split_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    const int old_vertex_count = static_cast<int>(result.vertices.size());
    result.copy_vertex_indices.reserve(result.vertices.size());
    for (int index = 0; index < old_vertex_count; ++index) {
        result.copy_vertex_indices.push_back(index);
    }
    std::map<std::array<int, 2>, int> edge_midpoints;
    std::set<int> changed;
    auto midpoint_index = [&](int a, int b) -> int {
        const std::array<int, 2> key = edge_key(a, b);
        const auto found = edge_midpoints.find(key);
        if (found != edge_midpoints.end()) {
            return found->second;
        }
        const Vec3 midpoint = scale_vec3(add_vec3(result.vertices[static_cast<std::size_t>(a)], result.vertices[static_cast<std::size_t>(b)]), 0.5);
        const int new_index = static_cast<int>(result.vertices.size());
        result.vertices.push_back(midpoint);
        result.copy_vertex_indices.push_back(-1);
        result.vertex_blends.push_back({new_index, a, b, 0.5});
        edge_midpoints[key] = new_index;
        changed.insert(new_index);
        ++result.added_vertices;
        return new_index;
    };

    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        const auto& face = original_faces[face_index];
        const int source_face_index = face_index < source_faces.size()
            ? source_faces[face_index]
            : static_cast<int>(face_index);
        if (split_faces.find(static_cast<int>(face_index)) == split_faces.end()) {
            result.faces.push_back(face);
            result.source_face_indices.push_back(source_face_index);
            continue;
        }
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const int ab = midpoint_index(a, b);
        const int bc = midpoint_index(b, c);
        const int ca = midpoint_index(c, a);
        changed.insert(a);
        changed.insert(b);
        changed.insert(c);
        changed.insert(ab);
        changed.insert(bc);
        changed.insert(ca);
        result.faces.push_back({a, ab, ca});
        result.faces.push_back({ab, b, bc});
        result.faces.push_back({ca, bc, c});
        result.faces.push_back({ab, bc, ca});
        result.source_face_indices.push_back(source_face_index);
        result.source_face_indices.push_back(source_face_index);
        result.source_face_indices.push_back(source_face_index);
        result.source_face_indices.push_back(source_face_index);
        result.added_faces += 3;
    }

    if (refine && !changed.empty()) {
        const double strength = std::max(0.0, std::min(1.0, number_or(edit.get("smooth_strength"), number_or(edit.get("strength"), 0.5))));
        const int iterations = std::max(1, std::min(12, int_or(edit.get("smooth_iterations"), int_or(edit.get("iterations"), 2))));
        std::vector<Vec3> relax = result.vertices;
        const std::vector<std::set<int>> adjacency = build_vertex_adjacency(result.vertices.size(), result.faces);
        for (int iteration = 0; iteration < iterations; ++iteration) {
            std::vector<Vec3> next = relax;
            for (const int index : changed) {
                if (index < 0 || static_cast<std::size_t>(index) >= adjacency.size()) {
                    continue;
                }
                const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(index)];
                if (neighbors.empty()) {
                    continue;
                }
                Vec3 sum{0.0, 0.0, 0.0};
                int count = 0;
                for (const int neighbor : neighbors) {
                    if (neighbor < 0 || static_cast<std::size_t>(neighbor) >= relax.size()) {
                        continue;
                    }
                    sum = add_vec3(sum, relax[static_cast<std::size_t>(neighbor)]);
                    ++count;
                }
                if (count <= 0) {
                    continue;
                }
                const Vec3 avg = scale_vec3(sum, 1.0 / static_cast<double>(count));
                const Vec3 vertex = relax[static_cast<std::size_t>(index)];
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(sub_vec3(avg, vertex), strength));
            }
            relax = std::move(next);
        }
        result.vertices = std::move(relax);
    }

    result.changed_vertices.assign(changed.begin(), changed.end());
    result.topology_changed = true;
    return result;
}

std::vector<Vec2> preview_uvs_for_result(const JsonValue& item, const SubmeshMeshEditResult& result) {
    if (result.vertices.empty()) {
        return {};
    }
    const std::vector<Vec2> input_uvs = mesh_uvs_from_item(item);
    if (input_uvs.empty()) {
        return std::vector<Vec2>(result.vertices.size(), {0.0, 0.0});
    }
    if (!result.topology_changed && input_uvs.size() == result.vertices.size()) {
        return input_uvs;
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<Vec2> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input_uvs.size()) {
            output.push_back(input_uvs[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend != blends.end()
            && blend->second.left >= 0
            && blend->second.right >= 0
            && static_cast<std::size_t>(blend->second.left) < input_uvs.size()
            && static_cast<std::size_t>(blend->second.right) < input_uvs.size()) {
            const Vec2 left = input_uvs[static_cast<std::size_t>(blend->second.left)];
            const Vec2 right = input_uvs[static_cast<std::size_t>(blend->second.right)];
            const double factor = std::max(0.0, std::min(1.0, blend->second.factor));
            output.push_back({
                left[0] + (right[0] - left[0]) * factor,
                left[1] + (right[1] - left[1]) * factor,
            });
            continue;
        }
        output.push_back({0.0, 0.0});
    }
    return output;
}

std::vector<Vec3> vec3_values_for_result(const std::vector<Vec3>& input, const SubmeshMeshEditResult& result) {
    if (input.empty()) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<Vec3> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.size()) {
            output.push_back(input[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend == blends.end()
            || blend->second.left < 0
            || blend->second.right < 0
            || static_cast<std::size_t>(blend->second.left) >= input.size()
            || static_cast<std::size_t>(blend->second.right) >= input.size()) {
            return {};
        }
        const Vec3 left = input[static_cast<std::size_t>(blend->second.left)];
        const Vec3 right = input[static_cast<std::size_t>(blend->second.right)];
        const double factor = std::max(0.0, std::min(1.0, blend->second.factor));
        output.push_back({
            left[0] + (right[0] - left[0]) * factor,
            left[1] + (right[1] - left[1]) * factor,
            left[2] + (right[2] - left[2]) * factor,
        });
    }
    return output;
}

std::vector<double> double_values_for_result(const std::vector<double>& input, const SubmeshMeshEditResult& result) {
    if (input.empty()) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<double> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.size()) {
            output.push_back(input[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend == blends.end()
            || blend->second.left < 0
            || blend->second.right < 0
            || static_cast<std::size_t>(blend->second.left) >= input.size()
            || static_cast<std::size_t>(blend->second.right) >= input.size()) {
            return {};
        }
        const double left = input[static_cast<std::size_t>(blend->second.left)];
        const double right = input[static_cast<std::size_t>(blend->second.right)];
        const double factor = std::max(0.0, std::min(1.0, blend->second.factor));
        output.push_back(left + (right - left) * factor);
    }
    return output;
}

bool valid_bone_assignments(const BoneAssignments& bones) {
    return !bones.indices.empty() && bones.indices.size() == bones.weights.size();
}

bool blended_bone_assignment(
    const BoneAssignments& input,
    int left,
    int right,
    double factor,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    if (!valid_bone_assignments(input)
        || left < 0
        || right < 0
        || static_cast<std::size_t>(left) >= input.indices.size()
        || static_cast<std::size_t>(right) >= input.indices.size()
        || input.indices[static_cast<std::size_t>(left)].size() != input.weights[static_cast<std::size_t>(left)].size()
        || input.indices[static_cast<std::size_t>(right)].size() != input.weights[static_cast<std::size_t>(right)].size()) {
        return false;
    }
    factor = std::max(0.0, std::min(1.0, factor));
    std::map<int, double> weights_by_bone;
    const std::vector<int>& left_indices = input.indices[static_cast<std::size_t>(left)];
    const std::vector<double>& left_weights = input.weights[static_cast<std::size_t>(left)];
    for (std::size_t index = 0; index < left_indices.size(); ++index) {
        const int bone = left_indices[index];
        const double weight = left_weights[index];
        if (bone >= 0 && weight > 0.0 && std::isfinite(weight)) {
            weights_by_bone[bone] += weight * (1.0 - factor);
        }
    }
    const std::vector<int>& right_indices = input.indices[static_cast<std::size_t>(right)];
    const std::vector<double>& right_weights = input.weights[static_cast<std::size_t>(right)];
    for (std::size_t index = 0; index < right_indices.size(); ++index) {
        const int bone = right_indices[index];
        const double weight = right_weights[index];
        if (bone >= 0 && weight > 0.0 && std::isfinite(weight)) {
            weights_by_bone[bone] += weight * factor;
        }
    }
    if (weights_by_bone.empty()) {
        out_indices.clear();
        out_weights.clear();
        return true;
    }
    std::vector<std::pair<int, double>> strongest(weights_by_bone.begin(), weights_by_bone.end());
    std::sort(strongest.begin(), strongest.end(), [](const auto& left_item, const auto& right_item) {
        if (left_item.second != right_item.second) {
            return left_item.second > right_item.second;
        }
        return left_item.first < right_item.first;
    });
    if (strongest.size() > 4) {
        strongest.resize(4);
    }
    double total = 0.0;
    for (const auto& item : strongest) {
        total += item.second;
    }
    if (total <= 0.0 || !std::isfinite(total)) {
        out_indices.clear();
        out_weights.clear();
        return true;
    }
    out_indices.clear();
    out_weights.clear();
    out_indices.reserve(strongest.size());
    out_weights.reserve(strongest.size());
    for (const auto& item : strongest) {
        out_indices.push_back(item.first);
        out_weights.push_back(item.second / total);
    }
    return true;
}

BoneAssignments bone_values_for_result(const BoneAssignments& input, const SubmeshMeshEditResult& result) {
    if (!valid_bone_assignments(input)) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    BoneAssignments output;
    output.indices.reserve(result.vertices.size());
    output.weights.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.indices.size()) {
            if (input.indices[static_cast<std::size_t>(source_index)].size() != input.weights[static_cast<std::size_t>(source_index)].size()) {
                return {};
            }
            output.indices.push_back(input.indices[static_cast<std::size_t>(source_index)]);
            output.weights.push_back(input.weights[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend == blends.end()) {
            return {};
        }
        std::vector<int> indices;
        std::vector<double> weights;
        if (!blended_bone_assignment(input, blend->second.left, blend->second.right, blend->second.factor, indices, weights)) {
            return {};
        }
        output.indices.push_back(std::move(indices));
        output.weights.push_back(std::move(weights));
    }
    return output;
}

std::vector<int> bone_assignment_counts(const BoneAssignments& bones) {
    std::vector<int> counts;
    if (!valid_bone_assignments(bones)) {
        return counts;
    }
    counts.reserve(bones.indices.size());
    for (std::size_t index = 0; index < bones.indices.size(); ++index) {
        if (bones.indices[index].size() != bones.weights[index].size() || bones.indices[index].size() > static_cast<std::size_t>(INT_MAX)) {
            return {};
        }
        counts.push_back(static_cast<int>(bones.indices[index].size()));
    }
    return counts;
}

std::vector<int> flatten_bone_indices(const BoneAssignments& bones) {
    std::vector<int> flat;
    if (!valid_bone_assignments(bones)) {
        return flat;
    }
    for (const std::vector<int>& vertex_indices : bones.indices) {
        flat.insert(flat.end(), vertex_indices.begin(), vertex_indices.end());
    }
    return flat;
}

std::vector<double> flatten_bone_weights(const BoneAssignments& bones) {
    std::vector<double> flat;
    if (!valid_bone_assignments(bones)) {
        return flat;
    }
    for (const std::vector<double>& vertex_weights : bones.weights) {
        flat.insert(flat.end(), vertex_weights.begin(), vertex_weights.end());
    }
    return flat;
}

std::vector<std::pair<int, double>> clean_weight_pairs_native(
    const std::vector<int>& raw_indices,
    const std::vector<double>& raw_weights
) {
    std::map<int, double> merged;
    const std::size_t count = std::min(raw_indices.size(), raw_weights.size());
    for (std::size_t index = 0; index < count; ++index) {
        const int bone = raw_indices[index];
        const double weight = raw_weights[index];
        if (bone >= 0 && weight > 0.0 && std::isfinite(weight)) {
            merged[bone] += weight;
        }
    }
    return std::vector<std::pair<int, double>>(merged.begin(), merged.end());
}
