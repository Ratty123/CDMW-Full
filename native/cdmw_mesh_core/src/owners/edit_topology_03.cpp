int next_generated_source_face_index(const std::vector<int>& source_faces) {
    int next = static_cast<int>(source_faces.size());
    for (const int index : source_faces) next = std::max(next, index + 1);
    return next;
}

Vec3 vertex_set_center(const std::vector<Vec3>& vertices, const std::set<int>& indices) {
    Vec3 center{0.0, 0.0, 0.0};
    for (const int index : indices) center = add_vec3(center, vertices[static_cast<std::size_t>(index)]);
    return scale_vec3(center, 1.0 / static_cast<double>(indices.size()));
}

// Corners split for a UV seam or hard normal share a position but not an index.
// Tools that must treat such a seam as joined key their vertices by these ids.
std::vector<int> coincident_position_ids(const std::vector<Vec3>& vertices) {
    std::map<std::array<long long, 3>, int> ids;
    std::vector<int> result(vertices.size(), 0);
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        const std::array<long long, 3> key{
            std::llround(vertices[index][0] * 1e7),
            std::llround(vertices[index][1] * 1e7),
            std::llround(vertices[index][2] * 1e7),
        };
        result[index] = ids.emplace(key, static_cast<int>(ids.size())).first->second;
    }
    return result;
}

SubmeshMeshEditResult extrude_selected_faces(
    SubmeshMeshEditResult result,
    const std::vector<std::array<int, 3>>& original_faces,
    const std::vector<int>& source_faces,
    const std::set<int>& selected_faces,
    const Vec3& offset
) {
    // Edges are counted by position, so a seam inside the selection is not read
    // as its border; that raised a pair of walls along the seam.
    const std::vector<int> position_ids = coincident_position_ids(result.vertices);
    std::map<std::array<int, 2>, int> edge_counts;
    std::vector<std::array<int, 2>> border_order;
    std::vector<std::array<int, 3>> selected_face_values;
    std::vector<int> selected_source_faces;
    std::set<int> selected_vertices;
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= original_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = original_faces[static_cast<std::size_t>(face_index)];
        selected_face_values.push_back(face);
        selected_source_faces.push_back(source_faces[static_cast<std::size_t>(face_index)]);
        for (int corner = 0; corner < 3; ++corner) {
            selected_vertices.insert(face[corner]);
            const int a = face[corner];
            const int b = face[(corner + 1) % 3];
            ++edge_counts[edge_key(position_ids[static_cast<std::size_t>(a)], position_ids[static_cast<std::size_t>(b)])];
            border_order.push_back({a, b});
        }
    }
    if (selected_face_values.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        return result;
    }
    const auto on_border = [&](int a, int b) {
        return edge_counts[edge_key(position_ids[static_cast<std::size_t>(a)], position_ids[static_cast<std::size_t>(b)])] == 1;
    };

    // A vertex on the border, or one an unselected face still uses, is copied
    // for the cap; every other selected vertex simply moves with it.
    std::set<int> copied;
    for (const auto& edge : border_order) {
        if (on_border(edge[0], edge[1])) {
            copied.insert(edge[0]);
            copied.insert(edge[1]);
        }
    }
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) == selected_faces.end()) {
            for (const int vertex_index : original_faces[face_index]) {
                if (selected_vertices.find(vertex_index) != selected_vertices.end()) {
                    copied.insert(vertex_index);
                }
            }
        }
    }
    std::map<int, int> cap_vertex;
    for (const int vertex_index : selected_vertices) {
        if (copied.find(vertex_index) == copied.end()) {
            result.vertices[static_cast<std::size_t>(vertex_index)] =
                add_vec3(result.vertices[static_cast<std::size_t>(vertex_index)], offset);
            result.changed_vertices.push_back(vertex_index);
            cap_vertex[vertex_index] = vertex_index;
            continue;
        }
        const int new_index = static_cast<int>(result.vertices.size());
        result.vertices.push_back(add_vec3(result.vertices[static_cast<std::size_t>(vertex_index)], offset));
        result.copy_vertex_indices.push_back(vertex_index);
        result.changed_vertices.push_back(new_index);
        cap_vertex[vertex_index] = new_index;
        ++result.added_vertices;
    }

    // The selected faces become the cap. Keeping them as well left a base
    // inside the extrusion and three faces on every border edge.
    result.faces.clear();
    result.source_face_indices.clear();
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) == selected_faces.end()) {
            result.faces.push_back(original_faces[face_index]);
            result.source_face_indices.push_back(source_faces[face_index]);
        }
    }
    for (std::size_t selected_index = 0; selected_index < selected_face_values.size(); ++selected_index) {
        const auto& face = selected_face_values[selected_index];
        result.faces.push_back({cap_vertex[face[0]], cap_vertex[face[1]], cap_vertex[face[2]]});
        result.source_face_indices.push_back(selected_source_faces[selected_index]);
        ++result.added_faces;
    }
    int next_generated_source_face = next_generated_source_face_index(source_faces);
    for (const auto& edge : border_order) {
        if (!on_border(edge[0], edge[1])) {
            continue;
        }
        // a -> b runs as the selected face ran it, the opposite of the neighbour
        // across the border, so each wall winds with the surface it joins.
        const int a = edge[0];
        const int b = edge[1];
        const int na = cap_vertex[a];
        const int nb = cap_vertex[b];
        result.faces.push_back({a, b, nb});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.faces.push_back({a, nb, na});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.added_faces += 2;
    }
    // A closed selection has no border and copies nothing; its cap still moved.
    result.topology_changed = result.added_faces > 0;
    if (!result.topology_changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.changed_vertices.clear();
    }
    return result;
}

SubmeshMeshEditResult run_extrude_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "extrude";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    if (source_faces.size() != original_faces.size()) {
        source_faces = identity_indices(original_faces.size());
    }
    const Vec3 offset = vec3_or(edit.get("offset"), vec3_or(edit.get("delta"), {0.0, 0.0, 0.25}));



    result.copy_vertex_indices.reserve(result.vertices.size());
    for (std::size_t vertex_index = 0; vertex_index < result.vertices.size(); ++vertex_index) {
        result.copy_vertex_indices.push_back(static_cast<int>(vertex_index));
    }

    // Faces only when faces are what was selected: deriving them from an edge
    // selection made "Extrude Edges" extrude the triangles beside each edge.
    std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    std::set<int> selected_faces = explicit_selected_faces_from_topology_json(item, original_faces.size());
    if (selected_faces.empty() && selected_edges.empty()) {
        selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    }
    if (!selected_faces.empty()) {
        return extrude_selected_faces(
            std::move(result), original_faces, source_faces, selected_faces, offset
        );
    }

    if (!original_faces.empty() && !selected_edges.empty()) {
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(original_faces);
        std::set<std::array<int, 2>> kept_edges;
        for (const auto& edge : selected_edges) {
            if (existing_edges.find(edge) != existing_edges.end()) {
                kept_edges.insert(edge);
            }
        }
        selected_edges = std::move(kept_edges);
    }
    if (selected_edges.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        return result;
    }

    // Each edge as the first face using it runs it. The new strip runs it the
    // other way, so it winds with that face instead of by vertex numbering.
    std::map<std::array<int, 2>, std::array<int, 2>> face_direction;
    for (const auto& face : original_faces) {
        for (int corner = 0; corner < 3; ++corner) {
            face_direction.emplace(edge_key(face[corner], face[(corner + 1) % 3]),
                std::array<int, 2>{face[corner], face[(corner + 1) % 3]});
        }
    }
    std::map<int, int> extruded_vertices;
    result.faces = original_faces;
    result.source_face_indices = source_faces;
    int next_generated_source_face = next_generated_source_face_index(source_faces);
    for (const auto& edge : selected_edges) {
        const auto direction = face_direction.find(edge);
        const int a = direction != face_direction.end() ? direction->second[1] : edge[0];
        const int b = direction != face_direction.end() ? direction->second[0] : edge[1];
        if (extruded_vertices.find(a) == extruded_vertices.end()) {
            const int new_index = static_cast<int>(result.vertices.size());
            result.vertices.push_back(add_vec3(result.vertices[static_cast<std::size_t>(a)], offset));
            result.copy_vertex_indices.push_back(a);
            result.changed_vertices.push_back(new_index);
            extruded_vertices[a] = new_index;
            ++result.added_vertices;
        }
        if (extruded_vertices.find(b) == extruded_vertices.end()) {
            const int new_index = static_cast<int>(result.vertices.size());
            result.vertices.push_back(add_vec3(result.vertices[static_cast<std::size_t>(b)], offset));
            result.copy_vertex_indices.push_back(b);
            result.changed_vertices.push_back(new_index);
            extruded_vertices[b] = new_index;
            ++result.added_vertices;
        }
        const int na = extruded_vertices[a];
        const int nb = extruded_vertices[b];
        result.faces.push_back({a, b, nb});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.faces.push_back({a, nb, na});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.added_faces += 2;
    }
    result.topology_changed = result.added_vertices > 0 && result.added_faces > 0;
    if (!result.topology_changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.changed_vertices.clear();
    }
    return result;
}

void clear_failed_inset_result(SubmeshMeshEditResult& result) {
    result.vertices.clear();
    result.faces.clear();
    result.copy_vertex_indices.clear();
    result.source_face_indices.clear();
    result.changed_vertices.clear();
}

SubmeshMeshEditResult run_inset_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "inset";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    double amount = number_or(edit.get("amount"), 0.25);
    amount = std::max(0.0, std::min(0.95, amount));
    if (amount <= 1.0e-8) {
        result.vertices.clear();
        return result;
    }

    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    if (source_faces.size() != original_faces.size()) {
        source_faces = identity_indices(original_faces.size());
    }

    const std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    if (selected_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<std::array<int, 3>> selected_face_values;
    std::vector<int> selected_source_faces;
    std::set<int> selected_vertices;
    selected_face_values.reserve(selected_faces.size());
    selected_source_faces.reserve(selected_faces.size());
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= original_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = original_faces[static_cast<std::size_t>(face_index)];
        selected_face_values.push_back(face);
        selected_source_faces.push_back(source_faces[static_cast<std::size_t>(face_index)]);
        selected_vertices.insert(face[0]);
        selected_vertices.insert(face[1]);
        selected_vertices.insert(face[2]);
    }
    if (selected_face_values.empty() || selected_vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    const Vec3 center = vertex_set_center(result.vertices, selected_vertices);

    result.copy_vertex_indices.reserve(result.vertices.size() + selected_vertices.size());
    for (std::size_t vertex_index = 0; vertex_index < result.vertices.size(); ++vertex_index) {
        result.copy_vertex_indices.push_back(static_cast<int>(vertex_index));
    }

    std::map<int, int> inner_vertices;
    std::map<std::array<int, 2>, int> edge_counts;
    std::map<std::array<int, 2>, std::array<int, 2>> edge_order;
    std::vector<std::array<int, 2>> edge_order_keys;
    for (const auto& face : selected_face_values) {
        for (const int vertex_index : face) {
            if (inner_vertices.find(vertex_index) != inner_vertices.end()) {
                continue;
            }
            const Vec3 vertex = result.vertices[static_cast<std::size_t>(vertex_index)];
            const Vec3 inset_vertex{
                vertex[0] + (center[0] - vertex[0]) * amount,
                vertex[1] + (center[1] - vertex[1]) * amount,
                vertex[2] + (center[2] - vertex[2]) * amount,
            };
            const int new_index = static_cast<int>(result.vertices.size());
            result.vertices.push_back(inset_vertex);
            result.copy_vertex_indices.push_back(vertex_index);
            result.changed_vertices.push_back(new_index);
            inner_vertices[vertex_index] = new_index;
            ++result.added_vertices;
        }
        const std::array<int, 2> oriented_edges[3] = {
            std::array<int, 2>{face[0], face[1]},
            std::array<int, 2>{face[1], face[2]},
            std::array<int, 2>{face[2], face[0]},
        };
        for (const auto& oriented : oriented_edges) {
            const std::array<int, 2> key = edge_key(oriented[0], oriented[1]);
            if (edge_counts.find(key) == edge_counts.end()) {
                edge_order_keys.push_back(key);
                edge_order[key] = oriented;
            }
            ++edge_counts[key];
        }
    }
    if (inner_vertices.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        result.changed_vertices.clear();
        return result;
    }

    result.faces.reserve(original_faces.size() + selected_face_values.size() + edge_order_keys.size() * 2);
    result.source_face_indices.reserve(original_faces.size() + selected_face_values.size() + edge_order_keys.size() * 2);
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        result.faces.push_back(original_faces[face_index]);
        result.source_face_indices.push_back(source_faces[face_index]);
    }
    for (std::size_t selected_index = 0; selected_index < selected_face_values.size(); ++selected_index) {
        const auto& face = selected_face_values[selected_index];
        result.faces.push_back({
            inner_vertices[face[0]],
            inner_vertices[face[1]],
            inner_vertices[face[2]],
        });
        result.source_face_indices.push_back(
            selected_index < selected_source_faces.size()
                ? selected_source_faces[selected_index]
                : static_cast<int>(selected_index)
        );
        ++result.added_faces;
    }

    int next_generated_source_face = next_generated_source_face_index(source_faces);
    for (const auto& edge : edge_order_keys) {
        if (edge_counts[edge] != 1) {
            continue;
        }
        const std::array<int, 2>& oriented = edge_order[edge];
        const int a = oriented[0];
        const int b = oriented[1];
        const int ia = inner_vertices[a];
        const int ib = inner_vertices[b];
        result.faces.push_back({a, b, ib});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.faces.push_back({a, ib, ia});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.added_faces += 2;
    }
    result.topology_changed = result.added_vertices > 0 && result.added_faces > 0;
    if (!result.topology_changed) {
        clear_failed_inset_result(result);
    }
    return result;
}

SubmeshMeshEditResult run_compact_orphans_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "compact_orphans";
    result.index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const JsonValue* raw_faces = item.get("faces");
    const JsonValue* raw_faces_binary = item.get("faces_binary");
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    const std::size_t raw_face_count = raw_faces_binary != nullptr
        ? faces.size()
        : raw_faces != nullptr && raw_faces->type == JsonValue::Type::Array
        ? raw_faces->array_value.size()
        : 0;
    if (result.index < 0 || vertices.empty()) {
        return result;
    }

    std::set<int> used_vertices;
    for (const auto& face : faces) {
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    const bool removed_invalid_faces = faces.size() != raw_face_count;
    if (used_vertices.size() == vertices.size() && !removed_invalid_faces) {
        return result;
    }

    std::map<int, int> index_map;
    for (const int old_index : used_vertices) {
        index_map[old_index] = static_cast<int>(result.vertices.size());
        result.vertices.push_back(vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const auto& face = faces[face_index];
        const auto a = index_map.find(face[0]);
        const auto b = index_map.find(face[1]);
        const auto c = index_map.find(face[2]);
        if (a != index_map.end() && b != index_map.end() && c != index_map.end()) {
            result.faces.push_back({a->second, b->second, c->second});
            result.source_face_indices.push_back(
                face_index < source_faces.size()
                    ? source_faces[face_index]
                    : static_cast<int>(face_index)
            );
        }
    }
    result.index_map.assign(vertices.size(), -1);
    for (const auto& item_map : index_map) {
        result.index_map[static_cast<std::size_t>(item_map.first)] = item_map.second;
    }
    result.removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(result.vertices.size());
    result.removed_faces = static_cast<int>(raw_face_count) - static_cast<int>(faces.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_split_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "split";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());

    std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    if (selected_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::set<int> selected_face_vertices;
    std::set<int> unselected_face_vertices;
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        const auto& face = original_faces[face_index];
        std::set<int>& target = selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()
            ? selected_face_vertices
            : unselected_face_vertices;
        target.insert(face[0]);
        target.insert(face[1]);
        target.insert(face[2]);
    }

    std::vector<int> shared_vertices;
    std::set_intersection(
        selected_face_vertices.begin(),
        selected_face_vertices.end(),
        unselected_face_vertices.begin(),
        unselected_face_vertices.end(),
        std::back_inserter(shared_vertices)
    );
    if (shared_vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    result.copy_vertex_indices.reserve(result.vertices.size() + shared_vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }

    std::map<int, int> split_map;
    for (const int vertex_index : shared_vertices) {
        const int new_index = static_cast<int>(result.vertices.size());
        result.vertices.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
        result.copy_vertex_indices.push_back(vertex_index);
        result.changed_vertices.push_back(new_index);
        split_map[vertex_index] = new_index;
        ++result.added_vertices;
    }

    result.faces.reserve(original_faces.size());
    result.source_face_indices.reserve(original_faces.size());
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        std::array<int, 3> face = original_faces[face_index];
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            for (int& vertex_index : face) {
                const auto found = split_map.find(vertex_index);
                if (found != split_map.end()) {
                    vertex_index = found->second;
                }
            }
        }
        result.faces.push_back(face);
        result.source_face_indices.push_back(
            face_index < source_faces.size()
                ? source_faces[face_index]
                : static_cast<int>(face_index)
        );
    }
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_edge_split_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "edge_split";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    result.copy_vertex_indices.reserve(result.vertices.size() + original_faces.size() * 3u);
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }

    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    result.faces.reserve(original_faces.size());
    result.source_face_indices.reserve(original_faces.size());
    if (!selected_edges.empty()) {
        // Each end of a selected edge gets one copy per wedge: the run of faces
        // around it that stay joined across unselected edges. Copying both ends
        // for the second face instead detached that face along its other two
        // edges too, so the split spread past the selection.
        std::map<int, std::vector<int>> faces_around;
        for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
            for (const int vertex_index : original_faces[face_index]) {
                faces_around[vertex_index].push_back(static_cast<int>(face_index));
            }
        }
        std::set<int> split_ends;
        for (const auto& edge : selected_edges) {
            split_ends.insert(edge[0]);
            split_ends.insert(edge[1]);
        }
        std::vector<std::array<int, 3>> faces = original_faces;
        for (const int vertex_index : split_ends) {
            const auto around = faces_around.find(vertex_index);
            if (around == faces_around.end()) {
                continue;
            }
            std::map<int, int> parent;
            for (const int face_index : around->second) {
                parent[face_index] = face_index;
            }
            const auto root = [&](int face_index) {
                while (parent[face_index] != face_index) {
                    parent[face_index] = parent[parent[face_index]];
                    face_index = parent[face_index];
                }
                return face_index;
            };
            std::map<int, std::vector<int>> faces_by_neighbour;
            for (const int face_index : around->second) {
                for (const int other : original_faces[static_cast<std::size_t>(face_index)]) {
                    if (other != vertex_index) {
                        faces_by_neighbour[other].push_back(face_index);
                    }
                }
            }
            for (const auto& joined : faces_by_neighbour) {
                if (selected_edges.find(edge_key(vertex_index, joined.first)) != selected_edges.end()) {
                    continue;
                }
                for (const int face_index : joined.second) {
                    parent[root(face_index)] = root(joined.second.front());
                }
            }
            std::map<int, std::vector<int>> wedges;
            for (const int face_index : around->second) {
                wedges[root(face_index)].push_back(face_index);
            }
            // The wedge holding the lowest face keeps the original vertex.
            std::vector<std::vector<int>> ordered;
            for (auto& wedge : wedges) {
                ordered.push_back(std::move(wedge.second));
            }
            std::sort(ordered.begin(), ordered.end());
            for (std::size_t wedge_index = 1; wedge_index < ordered.size(); ++wedge_index) {
                const int new_index = static_cast<int>(result.vertices.size());
                result.vertices.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                result.copy_vertex_indices.push_back(vertex_index);
                result.changed_vertices.push_back(new_index);
                ++result.added_vertices;
                for (const int face_index : ordered[wedge_index]) {
                    for (int corner = 0; corner < 3; ++corner) {
                        if (original_faces[static_cast<std::size_t>(face_index)][corner] == vertex_index) {
                            faces[static_cast<std::size_t>(face_index)][corner] = new_index;
                        }
                    }
                }
            }
        }
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            result.faces.push_back(faces[face_index]);
            result.source_face_indices.push_back(
                face_index < source_faces.size()
                    ? source_faces[face_index]
                    : static_cast<int>(face_index)
            );
        }
    } else {
        const std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
        if (selected_faces.empty()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
            std::array<int, 3> face = original_faces[face_index];
            if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
                for (int& vertex_index : face) {
                    const int new_index = static_cast<int>(result.vertices.size());
                    result.vertices.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                    result.copy_vertex_indices.push_back(vertex_index);
                    result.changed_vertices.push_back(new_index);
                    vertex_index = new_index;
                    ++result.added_vertices;
                }
            }
            result.faces.push_back(face);
            result.source_face_indices.push_back(
                face_index < source_faces.size()
                    ? source_faces[face_index]
                    : static_cast<int>(face_index)
            );
        }
    }
    result.topology_changed = result.added_vertices > 0;
    if (!result.topology_changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.changed_vertices.clear();
    }
    return result;
}

int loop_cut_count_from_edit(const JsonValue& edit) {
    const int value = int_or(edit.get("cuts"), int_or(edit.get("count"), int_or(edit.get("segments"), 1)));
    return std::max(1, std::min(16, value));
}

double loop_cut_factor_from_edit(const JsonValue* value) {
    const double parsed = number_or(value, 0.5);
    if (!std::isfinite(parsed)) {
        return 0.5;
    }
    return std::max(1.0e-6, std::min(1.0 - 1.0e-6, parsed));
}

std::vector<double> loop_cut_fractions_from_edit(const JsonValue& edit, int cut_count) {
    cut_count = std::max(1, std::min(16, cut_count));
    if (cut_count == 1 && (edit.get("factor") != nullptr || edit.get("position") != nullptr)) {
        return {loop_cut_factor_from_edit(edit.get("factor") != nullptr ? edit.get("factor") : edit.get("position"))};
    }
    std::vector<double> fractions;
    fractions.reserve(static_cast<std::size_t>(cut_count));
    for (int cut_index = 1; cut_index <= cut_count; ++cut_index) {
        fractions.push_back(static_cast<double>(cut_index) / static_cast<double>(cut_count + 1));
    }
    return fractions;
}

int append_loop_cut_vertex(SubmeshMeshEditResult& result, int left, int right, double fraction, std::set<int>& changed) {
    if (left < 0
        || right < 0
        || left == right
        || static_cast<std::size_t>(left) >= result.vertices.size()
        || static_cast<std::size_t>(right) >= result.vertices.size()) {
        return -1;
    }
    fraction = std::max(0.0, std::min(1.0, fraction));
    const Vec3 left_vertex = result.vertices[static_cast<std::size_t>(left)];
    const Vec3 right_vertex = result.vertices[static_cast<std::size_t>(right)];
    const int new_index = static_cast<int>(result.vertices.size());
    result.vertices.push_back({
        left_vertex[0] + (right_vertex[0] - left_vertex[0]) * fraction,
        left_vertex[1] + (right_vertex[1] - left_vertex[1]) * fraction,
        left_vertex[2] + (right_vertex[2] - left_vertex[2]) * fraction,
    });
    result.copy_vertex_indices.push_back(-1);
    result.vertex_blends.push_back({new_index, left, right, fraction});
    changed.insert(new_index);
    ++result.added_vertices;
    return new_index;
}

void append_loop_edge_cut_faces(
    std::vector<std::array<int, 3>>& out_faces,
    std::vector<int>& out_source_faces,
    const std::vector<int>& edge_vertices,
    int opposite_vertex,
    int source_face_index
) {
    if (edge_vertices.size() < 2) {
        return;
    }
    for (std::size_t index = 0; index + 1 < edge_vertices.size(); ++index) {
        out_faces.push_back({edge_vertices[index], edge_vertices[index + 1], opposite_vertex});
        out_source_faces.push_back(source_face_index);
    }
}
