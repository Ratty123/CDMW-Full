std::set<int> selected_faces_from_topology_json(
    const JsonValue& item,
    const std::vector<std::array<int, 3>>& faces,
    std::size_t vertex_count
) {
    std::set<int> selected_faces;
    const std::vector<int> source_faces = source_face_indices_for_selection(item, faces, vertex_count);
    const std::vector<int> explicit_selected_faces = int_vector_from_binary_or_json(
        item,
        "selected_faces_binary",
        "selected_faces",
        "selected_face_start",
        "selected_face_count"
    );
    for (const int index : explicit_selected_faces) {
        if (index >= 0) {
            selected_faces.insert(index);
        }
    }
    if (bool_or(item.get("selected_all_faces"), false)) {
        selected_faces.clear();
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            selected_faces.insert(static_cast<int>(face_index));
        }
        return selected_faces;
    }
    if (!selected_faces.empty()) {
        return compact_face_offsets_from_selection_values(selected_faces, source_faces, faces.size());
    }
    if (const MeshEditorSelection* selection = mesh_editor_selection_for_item(item)) {
        const int submesh_index = int_or(item.get("index"), -1);
        const auto found = selection->faces.find(submesh_index);
        if (found != selection->faces.end()) {
            selected_faces = compact_face_offsets_from_selection_values(found->second, source_faces, faces.size());
        }
        if (!selected_faces.empty()) {
            return selected_faces;
        }
    }

    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertex_count);
    if (!selected_edges.empty()) {
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            const auto& face = faces[face_index];
            if (selected_edges.find(edge_key(face[0], face[1])) != selected_edges.end()
                || selected_edges.find(edge_key(face[1], face[2])) != selected_edges.end()
                || selected_edges.find(edge_key(face[2], face[0])) != selected_edges.end()) {
                selected_faces.insert(static_cast<int>(face_index));
            }
        }
        return selected_faces;
    }

    const std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
    if (!selected_vertices.empty()) {
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            const auto& face = faces[face_index];
            if (selected_vertices.find(face[0]) != selected_vertices.end()
                || selected_vertices.find(face[1]) != selected_vertices.end()
                || selected_vertices.find(face[2]) != selected_vertices.end()) {
                selected_faces.insert(static_cast<int>(face_index));
            }
        }
    }
    return selected_faces;
}

std::set<std::array<int, 2>> face_edge_set(const std::vector<std::array<int, 3>>& faces);

std::set<int> selected_prune_faces_from_keys(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t selection_face_count,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<int>& source_faces
) {
    std::set<int> selected_faces = selected_indices_from_binary_or_json(
        item,
        binary_key,
        json_key,
        selection_face_count,
        json_key == "current_selected_faces" ? "current_selected_face_start" : "selected_face_start",
        json_key == "current_selected_faces" ? "current_selected_face_count" : "selected_face_count"
    );
    if (!selected_faces.empty()
        && source_faces.size() == faces.size()
        && selection_face_count > faces.size()) {
        std::set<int> kept_faces;
        for (std::size_t face_offset = 0; face_offset < faces.size(); ++face_offset) {
            const int source_face_index = source_faces[face_offset];
            if (selected_faces.find(source_face_index) != selected_faces.end()) {
                kept_faces.insert(source_face_index);
            }
        }
        selected_faces = std::move(kept_faces);
    }
    return selected_faces;
}

std::set<int> selected_vertices_from_edit_domains(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
) {
    std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
    if (bool_or(item.get("selected_all_vertices"), false)) {
        for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
            selected_vertices.insert(static_cast<int>(vertex_index));
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
    for (const auto& edge : selected_edges) {
        selected_vertices.insert(edge[0]);
        selected_vertices.insert(edge[1]);
    }

    if (bool_or(item.get("selected_all_faces"), false)) {
        for (const auto& face : faces) {
            selected_vertices.insert(face[0]);
            selected_vertices.insert(face[1]);
            selected_vertices.insert(face[2]);
        }
    }
    const std::set<int> selected_faces = selected_indices_from_binary_or_json(
        item,
        "selected_faces_binary",
        "selected_faces",
        faces.size(),
        "selected_face_start",
        "selected_face_count"
    );
    if (selected_faces.empty()) {
        const std::vector<int> source_faces = source_face_indices_for_selection(item, faces, vertex_count);
        if (const MeshEditorSelection* selection = mesh_editor_selection_for_item(item)) {
            const int submesh_index = int_or(item.get("index"), -1);
            const auto found = selection->faces.find(submesh_index);
            if (found != selection->faces.end()) {
                for (const int face_index : compact_face_offsets_from_selection_values(found->second, source_faces, faces.size())) {
                    if (face_index >= 0 && static_cast<std::size_t>(face_index) < faces.size()) {
                        selected_vertices.insert(faces[static_cast<std::size_t>(face_index)][0]);
                        selected_vertices.insert(faces[static_cast<std::size_t>(face_index)][1]);
                        selected_vertices.insert(faces[static_cast<std::size_t>(face_index)][2]);
                    }
                }
            }
        }
    }
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= faces.size()) {
            continue;
        }
        const auto& face = faces[static_cast<std::size_t>(face_index)];
        selected_vertices.insert(face[0]);
        selected_vertices.insert(face[1]);
        selected_vertices.insert(face[2]);
    }
    return selected_vertices;
}

std::set<std::array<int, 2>> face_edge_set(const std::vector<std::array<int, 3>>& faces) {
    std::set<std::array<int, 2>> result;
    for (const auto& face : faces) {
        result.insert(edge_key(face[0], face[1]));
        result.insert(edge_key(face[1], face[2]));
        result.insert(edge_key(face[2], face[0]));
    }
    return result;
}

std::vector<std::set<int>> build_vertex_adjacency(
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
);

std::set<int> mesh_editor_pruned_vertices_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    std::size_t vertex_count
) {
    std::set<int> result;
    const auto found = selection.vertices.find(submesh_index);
    if (found == selection.vertices.end()) {
        return result;
    }
    for (const int index : found->second) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.insert(index);
        }
    }
    return result;
}

std::map<int, double> mesh_editor_pruned_vertex_weights_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    const std::set<int>& allowed_vertices
) {
    std::map<int, double> result;
    const auto found = selection.vertex_weights.find(submesh_index);
    if (found == selection.vertex_weights.end()) {
        return result;
    }
    for (const auto& entry : found->second) {
        if (allowed_vertices.find(entry.first) != allowed_vertices.end()) {
            result[entry.first] = std::max(0.0, std::min(1.0, entry.second));
        }
    }
    return result;
}

std::set<std::array<int, 2>> mesh_editor_pruned_edges_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
) {
    std::set<std::array<int, 2>> result;
    const auto found = selection.edges.find(submesh_index);
    if (found == selection.edges.end()) {
        return result;
    }
    for (const std::array<int, 2>& edge : found->second) {
        if (edge[0] >= 0 && edge[1] >= 0 && edge[0] != edge[1]
            && static_cast<std::size_t>(edge[0]) < vertex_count
            && static_cast<std::size_t>(edge[1]) < vertex_count) {
            result.insert(edge_key(edge[0], edge[1]));
        }
    }
    if (!faces.empty() && !result.empty()) {
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
        std::set<std::array<int, 2>> kept;
        for (const std::array<int, 2>& edge : result) {
            if (existing_edges.find(edge) != existing_edges.end()) {
                kept.insert(edge);
            }
        }
        result = std::move(kept);
    }
    return result;
}

std::set<int> mesh_editor_pruned_faces_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    std::size_t face_count
) {
    std::set<int> result;
    const auto found = selection.faces.find(submesh_index);
    if (found == selection.faces.end()) {
        return result;
    }
    for (const int index : found->second) {
        if (index >= 0 && static_cast<std::size_t>(index) < face_count) {
            result.insert(index);
        }
    }
    return result;
}

std::set<int> mesh_editor_pruned_source_indices_for_session(
    const MeshEditorSession& session,
    const MeshEditorSelection& selection
) {
    std::set<int> result;
    for (const int index : selection.source_indices) {
        if (mesh_editor_submeshes(session).find(index) != mesh_editor_submeshes(session).end()) {
            result.insert(index);
        }
    }
    return result;
}

std::set<int> mesh_editor_selection_target_indices(const MeshEditorSelection& left, const MeshEditorSelection& right) {
    std::set<int> result;
    for (const auto& mapping : {left.vertices, right.vertices, left.faces, right.faces}) {
        for (const auto& entry : mapping) {
            if (entry.first >= 0) {
                result.insert(entry.first);
            }
        }
    }
    for (const auto& mapping : {left.edges, right.edges}) {
        for (const auto& entry : mapping) {
            if (entry.first >= 0) {
                result.insert(entry.first);
            }
        }
    }
    return result;
}

MeshEditorSelection mesh_editor_prune_and_combine_selection(
    const MeshEditorSession& session,
    const MeshEditorSelection& incoming,
    const std::string& operation
) {
    MeshEditorSelection result;
    result.source_indices = combine_selection_sets(
        mesh_editor_pruned_source_indices_for_session(session, session.selection),
        mesh_editor_pruned_source_indices_for_session(session, incoming),
        operation
    );
    const std::set<int> targets = mesh_editor_selection_target_indices(session.selection, incoming);
    for (const int submesh_index : targets) {
        const auto found = mesh_editor_submeshes(session).find(submesh_index);
        if (found == mesh_editor_submeshes(session).end()) {
            continue;
        }
        const MeshSessionSubmesh& submesh = found->second;
        const std::size_t vertex_count = submesh.vertices.size();
        const std::vector<std::array<int, 3>>& faces = submesh.faces;
        std::set<int> vertices = combine_selection_sets(
            mesh_editor_pruned_vertices_for_submesh(session.selection, submesh_index, vertex_count),
            mesh_editor_pruned_vertices_for_submesh(incoming, submesh_index, vertex_count),
            operation
        );
        if (!vertices.empty()) {
            std::map<int, double> weights;
            if (operation != "replace") {
                weights = mesh_editor_pruned_vertex_weights_for_submesh(session.selection, submesh_index, vertices);
            }
            if (operation != "subtract") {
                std::map<int, double> incoming_weights = mesh_editor_pruned_vertex_weights_for_submesh(incoming, submesh_index, vertices);
                for (const auto& entry : incoming_weights) {
                    weights[entry.first] = entry.second;
                }
            }
            if (!weights.empty()) {
                result.vertex_weights[submesh_index] = std::move(weights);
            }
            result.vertices[submesh_index] = std::move(vertices);
        }
        std::set<std::array<int, 2>> edges = combine_selection_sets(
            mesh_editor_pruned_edges_for_submesh(session.selection, submesh_index, vertex_count, faces),
            mesh_editor_pruned_edges_for_submesh(incoming, submesh_index, vertex_count, faces),
            operation
        );
        if (!edges.empty()) {
            result.edges[submesh_index] = std::move(edges);
        }
        std::set<int> selected_faces = combine_selection_sets(
            mesh_editor_pruned_faces_for_submesh(session.selection, submesh_index, faces.size()),
            mesh_editor_pruned_faces_for_submesh(incoming, submesh_index, faces.size()),
            operation
        );
        if (!selected_faces.empty()) {
            result.faces[submesh_index] = std::move(selected_faces);
        }
    }
    return result;
}

std::set<int> mesh_editor_vertices_from_selection_domains(
    const MeshEditorSelection& selection,
    int submesh_index,
    const MeshSessionSubmesh& submesh
) {
    std::set<int> selected = mesh_editor_pruned_vertices_for_submesh(selection, submesh_index, submesh.vertices.size());
    if (selection.source_indices.find(submesh_index) != selection.source_indices.end()) {
        for (std::size_t index = 0; index < submesh.vertices.size(); ++index) {
            selected.insert(static_cast<int>(index));
        }
    }
    std::set<std::array<int, 2>> selected_edges = mesh_editor_pruned_edges_for_submesh(selection, submesh_index, submesh.vertices.size(), submesh.faces);
    for (const std::array<int, 2>& edge : selected_edges) {
        selected.insert(edge[0]);
        selected.insert(edge[1]);
    }
    const std::set<int> selected_faces = mesh_editor_pruned_faces_for_submesh(selection, submesh_index, submesh.faces.size());
    for (const int face_index : selected_faces) {
        const std::array<int, 3>& face = submesh.faces[static_cast<std::size_t>(face_index)];
        selected.insert(face[0]);
        selected.insert(face[1]);
        selected.insert(face[2]);
    }
    return selected;
}

MeshEditorSelection mesh_editor_apply_selection_edit(
    const MeshEditorSession& session,
    const MeshEditorSelection& incoming,
    const std::string& operation,
    const std::string& target_mode,
    int iterations
) {
    MeshEditorSelection result;
    const bool all_operation = operation == "all";
    const bool invert_operation = operation == "invert";
    const bool source_target = target_mode == "source" || target_mode == "part";
    std::set<int> targets;
    if (all_operation || invert_operation || source_target) {
        targets.insert(incoming.source_indices.begin(), incoming.source_indices.end());
    }
    const auto append_map_targets = [&](const auto& values) {
        for (const auto& entry : values) {
            if (entry.first >= 0) targets.insert(entry.first);
        }
    };
    if (target_mode == "face") {
        append_map_targets(incoming.faces);
    } else if (target_mode == "edge") {
        append_map_targets(incoming.edges);
    } else if (!source_target) {
        append_map_targets(incoming.vertices);
    }
    for (const int submesh_index : targets) {
        const auto found = mesh_editor_submeshes(session).find(submesh_index);
        if (found == mesh_editor_submeshes(session).end()) {
            continue;
        }
        const MeshSessionSubmesh& submesh = found->second;
        if (submesh.vertices.empty()) {
            continue;
        }
        if (source_target) {
            if (all_operation || operation == "grow" || operation == "shrink" || operation == "smooth") {
                result.source_indices.insert(submesh_index);
            } else if (invert_operation) {
                for (const auto& entry : mesh_editor_submeshes(session)) {
                    if (incoming.source_indices.find(entry.first) == incoming.source_indices.end()) {
                        result.source_indices.insert(entry.first);
                    }
                }
            }
            continue;
        }
        if (all_operation) {
            if (target_mode == "face") {
                std::set<int>& faces = result.faces[submesh_index];
                for (std::size_t face_index = 0; face_index < submesh.faces.size(); ++face_index) {
                    faces.insert(static_cast<int>(face_index));
                }
                continue;
            }
            if (target_mode == "edge") {
                result.edges[submesh_index] = face_edge_set(submesh.faces);
                continue;
            }
            std::set<int>& selected = result.vertices[submesh_index];
            for (std::size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
                selected.insert(static_cast<int>(vertex_index));
            }
            continue;
        }
        if (target_mode == "face") {
            std::set<int> selected = mesh_editor_pruned_faces_for_submesh(
                incoming, submesh_index, submesh.faces.size()
            );
            if (invert_operation) {
                std::set<int> inverted;
                for (std::size_t index = 0; index < submesh.faces.size(); ++index) {
                    if (selected.find(static_cast<int>(index)) == selected.end()) {
                        inverted.insert(static_cast<int>(index));
                    }
                }
                selected = std::move(inverted);
            } else if (!selected.empty()) {
                std::vector<std::set<int>> adjacency(submesh.faces.size());
                std::map<std::array<int, 2>, std::vector<int>> edge_faces;
                for (std::size_t index = 0; index < submesh.faces.size(); ++index) {
                    const auto& face = submesh.faces[index];
                    for (const std::array<int, 2>& edge : {
                            edge_key(face[0], face[1]),
                            edge_key(face[1], face[2]),
                            edge_key(face[2], face[0])}) {
                        edge_faces[edge].push_back(static_cast<int>(index));
                    }
                }
                for (const auto& entry : edge_faces) {
                    for (const int left : entry.second) {
                        for (const int right : entry.second) {
                            if (left != right) adjacency[static_cast<std::size_t>(left)].insert(right);
                        }
                    }
                }
                for (int iteration = 0; iteration < std::max(0, iterations); ++iteration) {
                    std::set<int> next = operation == "grow" ? selected : std::set<int>{};
                    for (const int index : selected) {
                        const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(index)];
                        if (operation == "grow") {
                            next.insert(neighbors.begin(), neighbors.end());
                        } else if (operation == "shrink"
                                   && std::all_of(neighbors.begin(), neighbors.end(), [&](int neighbor) {
                                       return selected.find(neighbor) != selected.end();
                                   })) {
                            next.insert(index);
                        }
                    }
                    selected = std::move(next);
                }
            }
            if (!selected.empty()) result.faces[submesh_index] = std::move(selected);
            continue;
        }
        if (target_mode == "edge") {
            const std::set<std::array<int, 2>> all_edges = face_edge_set(submesh.faces);
            std::set<std::array<int, 2>> selected = mesh_editor_pruned_edges_for_submesh(
                incoming, submesh_index, submesh.vertices.size(), submesh.faces
            );
            if (invert_operation) {
                std::set<std::array<int, 2>> inverted;
                std::set_difference(
                    all_edges.begin(), all_edges.end(), selected.begin(), selected.end(),
                    std::inserter(inverted, inverted.end())
                );
                selected = std::move(inverted);
            } else if (!selected.empty()) {
                std::map<int, std::set<std::array<int, 2>>> incident;
                for (const auto& edge : all_edges) {
                    incident[edge[0]].insert(edge);
                    incident[edge[1]].insert(edge);
                }
                for (int iteration = 0; iteration < std::max(0, iterations); ++iteration) {
                    std::set<std::array<int, 2>> next = operation == "grow" ? selected : std::set<std::array<int, 2>>{};
                    for (const auto& edge : selected) {
                        std::set<std::array<int, 2>> neighbors = incident[edge[0]];
                        neighbors.insert(incident[edge[1]].begin(), incident[edge[1]].end());
                        neighbors.erase(edge);
                        if (operation == "grow") {
                            next.insert(neighbors.begin(), neighbors.end());
                        } else if (operation == "shrink"
                                   && std::all_of(neighbors.begin(), neighbors.end(), [&](const auto& neighbor) {
                                       return selected.find(neighbor) != selected.end();
                                   })) {
                            next.insert(edge);
                        }
                    }
                    selected = std::move(next);
                }
            }
            if (!selected.empty()) result.edges[submesh_index] = std::move(selected);
            continue;
        }
        std::set<int> selected = mesh_editor_pruned_vertices_for_submesh(
            incoming, submesh_index, submesh.vertices.size()
        );
        if (invert_operation) {
            std::set<int> inverted;
            for (std::size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
                if (selected.find(static_cast<int>(vertex_index)) == selected.end()) {
                    inverted.insert(static_cast<int>(vertex_index));
                }
            }
            selected = std::move(inverted);
        } else if (!selected.empty()) {
            const std::vector<std::set<int>> adjacency = build_vertex_adjacency(submesh.vertices.size(), submesh.faces);
            for (int iteration = 0; iteration < std::max(0, iterations); ++iteration) {
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
            result.vertices[submesh_index] = std::move(selected);
        }
    }
    return result;
}

Transform transform_from_json(const JsonValue& root) {
    const JsonValue* transform = root.get("transform");
    if (transform == nullptr || transform->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing transform object");
    }
    Transform result;
    result.axis = transform_axis_constraint(*transform);
    result.translate = vec3_or(transform->get("translate"), result.translate);
    result.scale = vec3_or(transform->get("scale"), result.scale);
    result.rotate = vec3_or(transform->get("rotate"), result.rotate);
    result.translate = constrain_vec3_axis(result.translate, result.axis, {0.0, 0.0, 0.0});
    result.scale = constrain_vec3_axis(result.scale, result.axis, {1.0, 1.0, 1.0});
    result.rotate = constrain_vec3_axis(result.rotate, result.axis, {0.0, 0.0, 0.0});
    result.pivot = vec3_or(transform->get("pivot"), result.pivot);
    result.snap = std::max(0.0, number_or(transform->get("snap"), 0.0));
    result.mirror_x = bool_or(transform->get("mirror_x"), false);
    result.pivot_from_selection = bool_or(transform->get("pivot_from_selection"), false);
    result.recompute_normals = bool_or(transform->get("recompute_normals"), true);
    return result;
}
