void finish_loop_cut_result(
    SubmeshMeshEditResult& result,
    const std::set<int>& changed,
    std::size_t original_face_count
) {
    if (changed.empty()) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.vertex_blends.clear();
        return;
    }
    result.changed_vertices.assign(changed.begin(), changed.end());
    result.added_faces = std::max(0, static_cast<int>(result.faces.size()) - static_cast<int>(original_face_count));
    result.topology_changed = true;
}

SubmeshMeshEditResult run_loop_cut_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "loop_cut";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    if (selected_edges.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    if (source_faces.size() != original_faces.size()) {
        source_faces = identity_indices(original_faces.size());
    }
    result.copy_vertex_indices.reserve(result.vertices.size() + selected_edges.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }

    const int cut_count = loop_cut_count_from_edit(edit);
    const std::vector<double> cut_fractions = loop_cut_fractions_from_edit(edit, cut_count);
    std::map<std::array<int, 2>, std::vector<int>> edge_cut_vertices;
    std::map<std::array<int, 2>, int> edge_midpoints;
    std::set<int> changed;

    auto cut_vertices = [&](int a, int b) -> std::vector<int> {
        const std::array<int, 2> key = edge_key(a, b);
        auto found = edge_cut_vertices.find(key);
        if (found == edge_cut_vertices.end()) {
            std::vector<int> vertices;
            vertices.reserve(cut_fractions.size());
            for (const double fraction : cut_fractions) {
                const int new_index = append_loop_cut_vertex(result, key[0], key[1], fraction, changed);
                if (new_index < 0) {
                    return std::vector<int>{};
                }
                vertices.push_back(new_index);
            }
            found = edge_cut_vertices.emplace(key, std::move(vertices)).first;
        }
        std::vector<int> vertices = found->second;
        if (key[0] != a || key[1] != b) {
            std::reverse(vertices.begin(), vertices.end());
        }
        return vertices;
    };

    auto cut_point = [&](int a, int b) -> int {
        const std::array<int, 2> key = edge_key(a, b);
        const auto found = edge_midpoints.find(key);
        if (found != edge_midpoints.end()) {
            return found->second;
        }
        const double fraction = cut_fractions.empty() ? 0.5 : cut_fractions[0];
        const int new_index = append_loop_cut_vertex(result, key[0], key[1], fraction, changed);
        if (new_index >= 0) {
            edge_midpoints[key] = new_index;
        }
        return new_index;
    };

    result.faces.reserve(original_faces.size() + selected_edges.size() * static_cast<std::size_t>(std::max(1, cut_count)));
    result.source_face_indices.reserve(result.faces.capacity());
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        const std::array<int, 3>& face = original_faces[face_index];
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const int source_face_index = source_faces[face_index];
        const std::array<int, 2> ab_key = edge_key(a, b);
        const std::array<int, 2> bc_key = edge_key(b, c);
        const std::array<int, 2> ca_key = edge_key(c, a);
        const bool has_ab = selected_edges.find(ab_key) != selected_edges.end();
        const bool has_bc = selected_edges.find(bc_key) != selected_edges.end();
        const bool has_ca = selected_edges.find(ca_key) != selected_edges.end();
        const int matched_count = (has_ab ? 1 : 0) + (has_bc ? 1 : 0) + (has_ca ? 1 : 0);
        if (matched_count <= 0) {
            result.faces.push_back(face);
            result.source_face_indices.push_back(source_face_index);
        } else if (matched_count == 1) {
            if (has_ab) {
                std::vector<int> edge_vertices{a};
                std::vector<int> cuts = cut_vertices(a, b);
                edge_vertices.insert(edge_vertices.end(), cuts.begin(), cuts.end());
                edge_vertices.push_back(b);
                append_loop_edge_cut_faces(result.faces, result.source_face_indices, edge_vertices, c, source_face_index);
            } else if (has_bc) {
                std::vector<int> edge_vertices{b};
                std::vector<int> cuts = cut_vertices(b, c);
                edge_vertices.insert(edge_vertices.end(), cuts.begin(), cuts.end());
                edge_vertices.push_back(c);
                append_loop_edge_cut_faces(result.faces, result.source_face_indices, edge_vertices, a, source_face_index);
            } else {
                std::vector<int> edge_vertices{c};
                std::vector<int> cuts = cut_vertices(c, a);
                edge_vertices.insert(edge_vertices.end(), cuts.begin(), cuts.end());
                edge_vertices.push_back(a);
                append_loop_edge_cut_faces(result.faces, result.source_face_indices, edge_vertices, b, source_face_index);
            }
        } else if (matched_count == 2) {
            if (has_ab && has_bc) {
                const int ab = cut_point(a, b);
                const int bc = cut_point(b, c);
                result.faces.push_back({ab, b, bc});
                result.faces.push_back({a, ab, bc});
                result.faces.push_back({a, bc, c});
            } else if (has_bc && has_ca) {
                const int bc = cut_point(b, c);
                const int ca = cut_point(c, a);
                result.faces.push_back({bc, c, ca});
                result.faces.push_back({a, b, bc});
                result.faces.push_back({a, bc, ca});
            } else {
                const int ca = cut_point(c, a);
                const int ab = cut_point(a, b);
                result.faces.push_back({ca, a, ab});
                result.faces.push_back({ab, b, c});
                result.faces.push_back({ab, c, ca});
            }
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
        } else {
            const int ab = cut_point(a, b);
            const int bc = cut_point(b, c);
            const int ca = cut_point(c, a);
            result.faces.push_back({a, ab, ca});
            result.faces.push_back({ab, b, bc});
            result.faces.push_back({ca, bc, c});
            result.faces.push_back({ab, bc, ca});
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
        }
    }

    finish_loop_cut_result(result, changed, original_faces.size());
    return result;
}

SubmeshMeshEditResult compact_remapped_edit_result(
    const std::string& action,
    int submesh_index,
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<int>& source_faces,
    const std::map<int, int>& remap,
    const std::map<int, Vec3>& moved_vertices
) {
    SubmeshMeshEditResult result;
    result.action = action;
    result.index = submesh_index;
    if (submesh_index < 0 || vertices.empty() || faces.empty()) {
        return result;
    }

    std::set<std::array<int, 3>> seen_faces;
    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    kept_faces.reserve(faces.size());
    kept_source_faces.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const std::array<int, 3>& face = faces[face_index];
        std::array<int, 3> remapped{
            remap.count(face[0]) ? remap.at(face[0]) : face[0],
            remap.count(face[1]) ? remap.at(face[1]) : face[1],
            remap.count(face[2]) ? remap.at(face[2]) : face[2],
        };
        if (remapped[0] == remapped[1] || remapped[1] == remapped[2] || remapped[0] == remapped[2]) {
            ++result.removed_faces;
            continue;
        }
        if (seen_faces.find(remapped) != seen_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        seen_faces.insert(remapped);
        kept_faces.push_back(remapped);
        kept_source_faces.push_back(
            face_index < source_faces.size()
                ? source_faces[face_index]
                : static_cast<int>(face_index)
        );
    }

    std::set<int> used_vertices;
    for (const std::array<int, 3>& face : kept_faces) {
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    std::map<int, int> compacted_by_old;
    result.vertices.reserve(used_vertices.size());
    result.copy_vertex_indices.reserve(used_vertices.size());
    for (const int old_index : used_vertices) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= vertices.size()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        compacted_by_old[old_index] = static_cast<int>(result.vertices.size());
        const auto moved = moved_vertices.find(old_index);
        result.vertices.push_back(moved != moved_vertices.end() ? moved->second : vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }

    result.faces.reserve(kept_faces.size());
    result.source_face_indices.reserve(kept_faces.size());
    for (std::size_t face_index = 0; face_index < kept_faces.size(); ++face_index) {
        const std::array<int, 3>& face = kept_faces[face_index];
        const auto a = compacted_by_old.find(face[0]);
        const auto b = compacted_by_old.find(face[1]);
        const auto c = compacted_by_old.find(face[2]);
        if (a == compacted_by_old.end() || b == compacted_by_old.end() || c == compacted_by_old.end()) {
            result.vertices.clear();
            result.faces.clear();
            result.copy_vertex_indices.clear();
            result.source_face_indices.clear();
            return result;
        }
        result.faces.push_back({a->second, b->second, c->second});
        result.source_face_indices.push_back(kept_source_faces[face_index]);
    }

    result.index_map.assign(vertices.size(), -1);
    for (std::size_t old_index = 0; old_index < vertices.size(); ++old_index) {
        const int remapped_old = remap.count(static_cast<int>(old_index))
            ? remap.at(static_cast<int>(old_index))
            : static_cast<int>(old_index);
        if (remapped_old != static_cast<int>(old_index)) {
            continue;
        }
        const auto found = compacted_by_old.find(static_cast<int>(old_index));
        if (found != compacted_by_old.end()) {
            result.index_map[old_index] = found->second;
        }
    }
    result.removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(result.vertices.size());

    bool moved = false;
    for (const auto& item_moved : moved_vertices) {
        if (item_moved.first >= 0
            && static_cast<std::size_t>(item_moved.first) < vertices.size()
            && !same_vec3(vertices[static_cast<std::size_t>(item_moved.first)], item_moved.second)) {
            moved = true;
            break;
        }
    }
    const bool changed = !remap.empty() || moved || result.removed_vertices > 0 || result.removed_faces > 0;
    if (!changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.index_map.clear();
        return result;
    }
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_merge_edit_for_submesh(const JsonValue& item) {
    const int submesh_index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() != faces.size()) {
        source_faces = identity_indices(faces.size());
    }
    SubmeshMeshEditResult empty;
    empty.action = "merge";
    empty.index = submesh_index;
    if (submesh_index < 0 || vertices.empty() || faces.empty()) {
        return empty;
    }

    const std::set<int> selected = selected_vertices_from_edit_domains(item, vertices.size(), faces);
    if (selected.size() < 2) {
        return empty;
    }
    const int keeper = *selected.begin();
    const Vec3 center = average_vertices(vertices, std::vector<int>(selected.begin(), selected.end()));
    std::map<int, int> remap;
    for (const int vertex_index : selected) {
        if (vertex_index != keeper) {
            remap[vertex_index] = keeper;
        }
    }
    std::map<int, Vec3> moved_vertices;
    moved_vertices[keeper] = center;
    return compact_remapped_edit_result("merge", submesh_index, vertices, faces, source_faces, remap, moved_vertices);
}

SubmeshMeshEditResult run_weld_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    const int submesh_index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() != faces.size()) {
        source_faces = identity_indices(faces.size());
    }
    SubmeshMeshEditResult empty;
    empty.action = "weld";
    empty.index = submesh_index;
    if (submesh_index < 0 || vertices.empty() || faces.empty()) {
        return empty;
    }

    const std::set<int> selected = selected_vertices_from_edit_domains(item, vertices.size(), faces);
    if (selected.size() < 2) {
        return empty;
    }
    double threshold = number_or(edit.get("threshold"), number_or(edit.get("distance"), number_or(edit.get("merge_distance"), 1e-5)));
    if (!std::isfinite(threshold) || threshold <= 0.0) {
        threshold = 1e-5;
    }
    const double threshold_squared = threshold * threshold;

    std::map<int, int> remap;
    std::map<int, Vec3> moved_vertices;
    const std::vector<int> sorted_indices(selected.begin(), selected.end());
    for (std::size_t position = 0; position < sorted_indices.size(); ++position) {
        const int keeper = sorted_indices[position];
        if (remap.find(keeper) != remap.end()) {
            continue;
        }
        std::vector<int> cluster{keeper};
        const Vec3& keeper_vertex = vertices[static_cast<std::size_t>(keeper)];
        for (std::size_t candidate_offset = position + 1; candidate_offset < sorted_indices.size(); ++candidate_offset) {
            const int candidate = sorted_indices[candidate_offset];
            if (remap.find(candidate) != remap.end()) {
                continue;
            }
            if (distance_squared_vec3(keeper_vertex, vertices[static_cast<std::size_t>(candidate)]) <= threshold_squared) {
                cluster.push_back(candidate);
            }
        }
        if (cluster.size() < 2) {
            continue;
        }
        moved_vertices[keeper] = average_vertices(vertices, cluster);
        for (std::size_t cluster_index = 1; cluster_index < cluster.size(); ++cluster_index) {
            remap[cluster[cluster_index]] = keeper;
        }
    }
    if (remap.empty()) {
        return empty;
    }
    return compact_remapped_edit_result("weld", submesh_index, vertices, faces, source_faces, remap, moved_vertices);
}

SubmeshMeshEditResult run_duplicate_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "duplicate";
    result.index = int_or(item.get("index"), -1);
    result.source_index = result.index;
    result.name_suffix = " duplicate";
    const std::vector<Vec3> source_vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> source_faces = mesh_faces_from_item(item, source_vertices.size());
    if (result.index < 0 || source_vertices.empty() || source_faces.empty()) {
        return result;
    }
    const std::vector<int> source_face_indices = mesh_source_face_indices_from_item(item, source_faces.size());
    const std::set<int> selected_faces = selected_faces_from_topology_json(item, source_faces, source_vertices.size());
    if (selected_faces.empty()) {
        return result;
    }

    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    std::set<int> used_vertices;
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= source_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = source_faces[static_cast<std::size_t>(face_index)];
        kept_faces.push_back(face);
        kept_source_faces.push_back(
            static_cast<std::size_t>(face_index) < source_face_indices.size()
                ? source_face_indices[static_cast<std::size_t>(face_index)]
                : face_index
        );
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    if (kept_faces.empty() || used_vertices.empty()) {
        return result;
    }

    std::map<int, int> remap;
    result.vertices.reserve(used_vertices.size());
    result.copy_vertex_indices.reserve(used_vertices.size());
    for (const int old_index : used_vertices) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        const int new_index = static_cast<int>(result.vertices.size());
        remap[old_index] = new_index;
        result.vertices.push_back(source_vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }

    result.faces.reserve(kept_faces.size());
    result.source_face_indices.reserve(kept_faces.size());
    for (std::size_t face_index = 0; face_index < kept_faces.size(); ++face_index) {
        const std::array<int, 3>& face = kept_faces[face_index];
        const auto a = remap.find(face[0]);
        const auto b = remap.find(face[1]);
        const auto c = remap.find(face[2]);
        if (a == remap.end() || b == remap.end() || c == remap.end()) {
            continue;
        }
        result.faces.push_back({a->second, b->second, c->second});
        result.source_face_indices.push_back(kept_source_faces[face_index]);
    }
    if (result.faces.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        return result;
    }

    result.append_submesh = true;
    result.added_vertices = static_cast<int>(result.vertices.size());
    result.added_faces = static_cast<int>(result.faces.size());
    result.topology_changed = true;
    return result;
}

int mirror_axis_index_from_edit(const JsonValue& edit) {
    std::string axis = string_or(edit.get("axis"), "x");
    std::transform(axis.begin(), axis.end(), axis.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (axis == "y" || axis == "1") {
        return 1;
    }
    if (axis == "z" || axis == "2") {
        return 2;
    }
    return 0;
}

Vec3 mirrored_vec3_axis(Vec3 value, int axis_index) {
    if (axis_index < 0 || axis_index > 2) {
        axis_index = 0;
    }
    value[static_cast<std::size_t>(axis_index)] = -value[static_cast<std::size_t>(axis_index)];
    return value;
}

SubmeshMeshEditResult run_mirror_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "mirror";
    result.index = int_or(item.get("index"), -1);
    result.source_index = result.index;
    result.name_suffix = " mirror";
    result.mirror_axis_index = mirror_axis_index_from_edit(edit);
    const std::vector<Vec3> source_vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> source_faces = mesh_faces_from_item(item, source_vertices.size());
    if (result.index < 0 || source_vertices.empty() || source_faces.empty()) {
        return result;
    }
    const std::vector<int> source_face_indices = mesh_source_face_indices_from_item(item, source_faces.size());
    const std::set<int> selected_faces = selected_faces_from_topology_json(item, source_faces, source_vertices.size());
    if (selected_faces.empty()) {
        return result;
    }

    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    std::set<int> used_vertices;
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= source_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = source_faces[static_cast<std::size_t>(face_index)];
        kept_faces.push_back(face);
        kept_source_faces.push_back(
            static_cast<std::size_t>(face_index) < source_face_indices.size()
                ? source_face_indices[static_cast<std::size_t>(face_index)]
                : face_index
        );
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    if (kept_faces.empty() || used_vertices.empty()) {
        return result;
    }

    std::map<int, int> remap;
    result.vertices.reserve(used_vertices.size());
    result.copy_vertex_indices.reserve(used_vertices.size());
    for (const int old_index : used_vertices) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        const int new_index = static_cast<int>(result.vertices.size());
        remap[old_index] = new_index;
        result.vertices.push_back(mirrored_vec3_axis(source_vertices[static_cast<std::size_t>(old_index)], result.mirror_axis_index));
        result.copy_vertex_indices.push_back(old_index);
    }

    result.faces.reserve(kept_faces.size());
    result.source_face_indices.reserve(kept_faces.size());
    for (std::size_t face_index = 0; face_index < kept_faces.size(); ++face_index) {
        const std::array<int, 3>& face = kept_faces[face_index];
        const auto a = remap.find(face[0]);
        const auto b = remap.find(face[1]);
        const auto c = remap.find(face[2]);
        if (a == remap.end() || b == remap.end() || c == remap.end()) {
            continue;
        }
        result.faces.push_back({a->second, c->second, b->second});
        result.source_face_indices.push_back(kept_source_faces[face_index]);
    }
    if (result.faces.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        return result;
    }

    result.append_submesh = true;
    result.added_vertices = static_cast<int>(result.vertices.size());
    result.added_faces = static_cast<int>(result.faces.size());
    result.topology_changed = true;
    return result;
}

std::vector<SubmeshMeshEditResult> run_separate_edit_for_submesh(const JsonValue& item) {
    const int source_index = int_or(item.get("index"), -1);
    const std::vector<Vec3> source_vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> source_faces = mesh_faces_from_item(item, source_vertices.size());
    if (source_index < 0 || source_vertices.empty() || source_faces.empty()) {
        return {};
    }
    const std::vector<int> source_face_indices = mesh_source_face_indices_from_item(item, source_faces.size());
    const std::set<int> selected_faces = selected_faces_from_topology_json(item, source_faces, source_vertices.size());
    if (selected_faces.empty()) {
        return {};
    }

    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    std::vector<std::array<int, 3>> moved_faces;
    std::vector<int> moved_source_faces;
    for (std::size_t face_index = 0; face_index < source_faces.size(); ++face_index) {
        const int source_face = face_index < source_face_indices.size()
            ? source_face_indices[face_index]
            : static_cast<int>(face_index);
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            moved_faces.push_back(source_faces[face_index]);
            moved_source_faces.push_back(source_face);
        } else {
            kept_faces.push_back(source_faces[face_index]);
            kept_source_faces.push_back(source_face);
        }
    }
    if (moved_faces.empty()) {
        return {};
    }

    auto compact_faces = [&](const std::vector<std::array<int, 3>>& faces) {
        SubmeshMeshEditResult result;
        std::set<int> used_vertices;
        for (const auto& face : faces) {
            used_vertices.insert(face[0]);
            used_vertices.insert(face[1]);
            used_vertices.insert(face[2]);
        }
        std::map<int, int> remap;
        result.vertices.reserve(used_vertices.size());
        result.copy_vertex_indices.reserve(used_vertices.size());
        for (const int old_index : used_vertices) {
            if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
                result.vertices.clear();
                result.copy_vertex_indices.clear();
                result.faces.clear();
                return result;
            }
            const int new_index = static_cast<int>(result.vertices.size());
            remap[old_index] = new_index;
            result.vertices.push_back(source_vertices[static_cast<std::size_t>(old_index)]);
            result.copy_vertex_indices.push_back(old_index);
        }
        result.faces.reserve(faces.size());
        for (const auto& face : faces) {
            const auto a = remap.find(face[0]);
            const auto b = remap.find(face[1]);
            const auto c = remap.find(face[2]);
            if (a == remap.end() || b == remap.end() || c == remap.end()) {
                result.vertices.clear();
                result.copy_vertex_indices.clear();
                result.faces.clear();
                return result;
            }
            result.faces.push_back({a->second, b->second, c->second});
        }
        return result;
    };

    SubmeshMeshEditResult source_result = compact_faces(kept_faces);
    if (!kept_faces.empty() && source_result.faces.empty()) {
        return {};
    }
    source_result.action = "separate";
    source_result.index = source_index;
    source_result.source_face_indices = kept_source_faces;
    source_result.removed_faces = static_cast<int>(moved_faces.size());
    source_result.removed_vertices = static_cast<int>(source_vertices.size()) - static_cast<int>(source_result.vertices.size());
    source_result.topology_changed = true;

    SubmeshMeshEditResult append_result = compact_faces(moved_faces);
    if (append_result.faces.empty()) {
        return {};
    }
    append_result.action = "separate";
    append_result.index = source_index;
    append_result.append_submesh = true;
    append_result.source_index = source_index;
    append_result.name_suffix = " split";
    append_result.source_face_indices = moved_source_faces;
    append_result.added_vertices = static_cast<int>(append_result.vertices.size());
    append_result.added_faces = static_cast<int>(append_result.faces.size());
    append_result.topology_changed = true;

    return {std::move(source_result), std::move(append_result)};
}

SubmeshMeshEditResult run_fix_winding_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "fix_winding";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    const std::vector<Vec3> normals = mesh_normals_from_item(item);
    if (result.index < 0 || result.vertices.empty() || original_faces.empty() || normals.size() != result.vertices.size()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    result.faces = original_faces;
    result.source_face_indices = source_faces.size() == original_faces.size()
        ? source_faces
        : identity_indices(original_faces.size());
    result.copy_vertex_indices.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }
    bool changed = false;
    for (std::array<int, 3>& face : result.faces) {
        const Vec3 face_normal = normalized_vec3(
            face_cross(
                result.vertices[static_cast<std::size_t>(face[0])],
                result.vertices[static_cast<std::size_t>(face[1])],
                result.vertices[static_cast<std::size_t>(face[2])]
            ),
            {0.0, 0.0, 0.0}
        );
        const Vec3 average_normal = normalized_vec3(
            add_vec3(
                add_vec3(normals[static_cast<std::size_t>(face[0])], normals[static_cast<std::size_t>(face[1])]),
                normals[static_cast<std::size_t>(face[2])]
            ),
            {0.0, 0.0, 0.0}
        );
        if (dot_vec3(face_normal, average_normal) < -1.0e-8) {
            std::swap(face[1], face[2]);
            changed = true;
        }
    }
    if (!changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        return result;
    }
    result.topology_changed = true;
    return result;
}
