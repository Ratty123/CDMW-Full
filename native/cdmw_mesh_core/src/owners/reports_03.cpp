std::vector<SubmeshSelectionPreviewResult> mesh_editor_selection_preview_report_items(
    const MeshEditorSession& session,
    const std::string& output_dir,
    const std::string& session_id
) {
    std::set<int> targets = session.selection.source_indices;
    for (const auto& mapping : {session.selection.vertices, session.selection.faces}) {
        for (const auto& entry : mapping) {
            targets.insert(entry.first);
        }
    }
    for (const auto& entry : session.selection.edges) {
        targets.insert(entry.first);
    }

    std::vector<SubmeshSelectionPreviewResult> results;
    for (const int submesh_index : targets) {
        const auto submesh_found = mesh_editor_submeshes(session).find(submesh_index);
        if (submesh_found == mesh_editor_submeshes(session).end()) {
            continue;
        }
        const MeshSessionSubmesh& submesh = submesh_found->second;
        const std::size_t vertex_count = submesh.vertices.size();
        if (vertex_count == 0) {
            continue;
        }
        std::set<int> source_vertices;
        std::set<std::array<int, 2>> source_edges;
        std::set<int> source_faces;

        if (session.selection.source_indices.find(submesh_index) != session.selection.source_indices.end()) {
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                source_vertices.insert(static_cast<int>(vertex_index));
            }
        }
        const auto vertices = session.selection.vertices.find(submesh_index);
        if (vertices != session.selection.vertices.end()) {
            for (const int vertex_index : vertices->second) {
                if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < vertex_count) {
                    source_vertices.insert(vertex_index);
                }
            }
        }
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(submesh.faces);
        const auto edges = session.selection.edges.find(submesh_index);
        if (edges != session.selection.edges.end()) {
            for (const auto& edge : edges->second) {
                if (edge[0] < 0 || edge[1] < 0
                    || static_cast<std::size_t>(edge[0]) >= vertex_count
                    || static_cast<std::size_t>(edge[1]) >= vertex_count
                    || edge[0] == edge[1]) {
                    continue;
                }
                if (!submesh.faces.empty() && existing_edges.find(edge) == existing_edges.end()) {
                    continue;
                }
                source_edges.insert(edge);
                source_vertices.insert(edge[0]);
                source_vertices.insert(edge[1]);
            }
        }
        const auto faces = session.selection.faces.find(submesh_index);
        if (faces != session.selection.faces.end()) {
            for (const int face_index : faces->second) {
                if (face_index < 0 || static_cast<std::size_t>(face_index) >= submesh.faces.size()) {
                    continue;
                }
                source_faces.insert(face_index);
                const auto& face = submesh.faces[static_cast<std::size_t>(face_index)];
                source_vertices.insert(face[0]);
                source_vertices.insert(face[1]);
                source_vertices.insert(face[2]);
            }
        }
        if (source_vertices.empty()) {
            continue;
        }
        SubmeshSelectionPreviewResult result;
        result.index = submesh_index;
        result.source_vertex_indices.assign(source_vertices.begin(), source_vertices.end());
        result.source_edges.assign(source_edges.begin(), source_edges.end());
        result.source_face_indices.assign(source_faces.begin(), source_faces.end());
        if (!output_dir.empty()) {
            result.selection_preview_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_preview", ".bin");
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::string mesh_editor_select_report_json(
    const MeshEditorSession& session,
    const std::string& session_id,
    const std::string& selection_operation,
    const std::string& output_dir,
    double cpp_ms,
    int source_pick_count = -1
) {
    const std::vector<SubmeshSelectionPruneResult> results = mesh_editor_selection_report_items(session.selection, output_dir, session_id);
    const std::vector<SubmeshSelectionPreviewResult> selection_groups =
        mesh_editor_selection_preview_report_items(session, output_dir, session_id);
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"select\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"selection_operation\":";
    write_escaped(out, selection_operation);
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    std::size_t selected_vertex_count = 0;
    std::size_t selected_edge_count = 0;
    std::size_t selected_face_count = 0;
    for (const auto& entry : mesh_editor_submeshes(session)) {
        vertex_count += entry.second.vertices.size();
        face_count += entry.second.faces.size();
    }
    for (const auto& entry : session.selection.vertices) {
        selected_vertex_count += entry.second.size();
    }
    for (const auto& entry : session.selection.edges) {
        selected_edge_count += entry.second.size();
    }
    for (const auto& entry : session.selection.faces) {
        selected_face_count += entry.second.size();
    }
    out << ",\"submesh_count\":" << mesh_editor_submeshes(session).size()
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"topology_revision\":" << session.topology_revision
        << ",\"selection_revision\":" << session.selection_revision
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"stroke_revision\":" << session.stroke_revision
        << ",\"active_stroke\":" << (session.active_stroke.active ? "true" : "false")
        << ",\"selected_vertex_count\":" << selected_vertex_count
        << ",\"selected_edge_count\":" << selected_edge_count
        << ",\"selected_face_count\":" << selected_face_count;
    out << ",\"source_indices\":";
    write_int_vector(out, std::vector<int>(session.selection.source_indices.begin(), session.selection.source_indices.end()));
    if (source_pick_count >= 0) {
        out << ",\"source_pick_count\":" << source_pick_count;
    }
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_selection_prune_item(out, results[i]);
    }
    out << "],\"selection_groups\":[";
    for (std::size_t i = 0; i < selection_groups.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_selection_preview_group(out, selection_groups[i]);
    }
    out << "],";
    write_command_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

void write_changed_vertices_report(
    std::ostream& out,
    const std::vector<int>& changed_vertices,
    const std::string& changed_vertices_path,
    int& changed_vertex_start
) {
    changed_vertex_start = -1;
    if (changed_vertices.empty()) {
        out << ",\"changed_vertex_start\":0,\"changed_vertex_count\":0";
        return;
    }
    if (contiguous_int_range(changed_vertices, changed_vertex_start)) {
        out << ",\"changed_vertex_start\":" << changed_vertex_start
            << ",\"changed_vertex_count\":" << changed_vertices.size();
        return;
    }
    changed_vertex_start = -1;
    if (!changed_vertices_path.empty()) {
        write_int_binary_file(changed_vertices_path, changed_vertices);
        out << ",\"changed_vertices_binary\":";
        write_int_binary_descriptor(out, changed_vertices_path, changed_vertices.size(), 1);
        return;
    }
    out << ",\"changed_vertices\":";
    write_int_vector(out, changed_vertices);
}

std::string transform_report_json(const std::vector<SubmeshTransformResult>& results, const std::string& operation = "transform") {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, operation);
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshTransformResult& result = results[i];
        out << "{\"index\":" << result.index;
        if (result.resident_sparse) out << ",\"resident_sparse\":true";
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.before_positions.empty() && !result.before_positions_path.empty() && result.before_positions.size() == result.changed_vertices.size()) {
            write_vec3_binary_file(result.before_positions_path, result.before_positions);
            out << ",\"before_positions_binary\":";
            write_vec3_binary_descriptor(out, result.before_positions_path, result.before_positions.size());
        }
        if (!result.sparse_snapshot_id.empty() && result.before_positions.size() == result.changed_vertices.size()) {
            out << ",\"native_sparse_snapshot_id\":";
            write_escaped(out, result.sparse_snapshot_id);
        }
        if (result.sparse) {
            if (!result.changed_positions_path.empty()) {
                write_vec3_binary_file(result.changed_positions_path, result.changed_positions);
                out << ",\"changed_positions_binary\":";
                write_vec3_binary_descriptor(out, result.changed_positions_path, result.changed_positions.size());
            } else {
                out << ",\"changed_positions\":[";
                for (std::size_t j = 0; j < result.changed_positions.size(); ++j) {
                    if (j) {
                        out << ',';
                    }
                    write_vec3(out, result.changed_positions[j]);
                }
                out << "]";
            }
        } else {
            out << ",\"vertices\":[";
            for (std::size_t j = 0; j < result.vertices.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec3(out, result.vertices[j]);
            }
            out << "]";
        }
        out << ",\"preview_vertex_update_group\":";
        if (result.sparse) {
            write_sparse_preview_vertex_update_group(
                out,
                result.index,
                result.changed_vertices,
                result.changed_positions,
                {},
                {},
                result.changed_positions_path,
                changed_vertex_start,
                result.source_vertex_map,
                result.changed_source_vertex_ids
            );
        } else {
            write_preview_vertex_update_group(
                out,
                result.index,
                result.changed_vertices,
                result.vertices,
                {},
                {},
                result.changed_vertices_path,
                result.source_vertex_map
            );
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string uv_transform_report_json(const std::vector<SubmeshUvTransformResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"uv_transform\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshUvTransformResult& result = results[i];
        out << "{\"index\":" << result.index;
        if (result.status != "ok") {
            out << ",\"status\":";
            write_escaped(out, result.status);
            if (!result.error.empty()) {
                out << ",\"error\":";
                write_escaped(out, result.error);
            }
            out << ",\"invalid_vertex_index\":" << result.invalid_vertex_index
                << ",\"invalid_uv\":";
            write_vec2(out, result.invalid_uv);
            out << "}";
            continue;
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (result.clear_uvs) {
            out << ",\"clear_uvs\":true}";
            continue;
        }
        if (!result.uvs_path.empty()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        } else {
            out << ",\"uvs\":[";
            for (std::size_t j = 0; j < result.uvs.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec2(out, result.uvs[j]);
            }
            out << ']';
        }
        if (!result.changed_vertices.empty() && result.vertices.size() == result.uvs.size()) {
            std::vector<Vec3> changed_positions;
            changed_positions.reserve(result.changed_vertices.size());
            for (const int vertex_index : result.changed_vertices) {
                if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= result.vertices.size()) {
                    changed_positions.clear();
                    break;
                }
                changed_positions.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
            }
            if (changed_positions.size() == result.changed_vertices.size()) {
                out << ",\"preview_vertex_update_group\":";
                write_sparse_preview_vertex_update_group(
                    out,
                    result.index,
                    result.changed_vertices,
                    changed_positions,
                    result.normals,
                    result.uvs,
                    result.preview_vertex_path,
                    changed_vertex_start
                );
            }
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string auto_uv_report_json(const std::vector<SubmeshAutoUvResult>& results) {
    std::ostringstream out;
    bool topology_changed = false;
    for (const SubmeshAutoUvResult& result : results) {
        topology_changed = topology_changed || result.topology_changed;
    }
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"auto_uv\",\"unwrap_backend\":\"xatlas\",\"topology_changed\":" << (topology_changed ? "true" : "false") << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshAutoUvResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"status\":";
        write_escaped(out, result.status);
        out << ",\"unwrap_backend\":\"xatlas\""
            << ",\"topology_changed\":" << (result.topology_changed ? "true" : "false")
            << ",\"input_vertex_count\":" << result.input_vertex_count
            << ",\"output_vertex_count\":" << result.output_vertex_count
            << ",\"input_face_count\":" << result.input_face_count
            << ",\"output_face_count\":" << result.output_face_count
            << ",\"chart_count\":" << result.chart_count;
        if (!result.error.empty()) {
            out << ",\"error\":";
            write_escaped(out, result.error);
        }
        if (!result.vertex_remap_path.empty()) {
            write_int_binary_file(result.vertex_remap_path, result.vertex_remap);
            out << ",\"vertex_remap_binary\":";
            write_int_binary_descriptor(out, result.vertex_remap_path, result.vertex_remap.size(), 1);
        } else {
            out << ",\"vertex_remap\":[";
            for (std::size_t j = 0; j < result.vertex_remap.size(); ++j) {
                if (j) {
                    out << ',';
                }
                out << result.vertex_remap[j];
            }
            out << ']';
        }
        if (!result.faces_path.empty()) {
            write_faces_binary_file(result.faces_path, result.faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
        } else {
            out << ",\"faces\":[";
            for (std::size_t j = 0; j < result.faces.size(); ++j) {
                if (j) {
                    out << ',';
                }
                out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
            }
            out << ']';
        }
        if (!result.uvs_path.empty()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        } else {
            out << ",\"uvs\":[";
            for (std::size_t j = 0; j < result.uvs.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec2(out, result.uvs[j]);
            }
            out << ']';
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.vertices_path.empty() && result.vertices.size() == result.vertex_remap.size()) {
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        }
        if (!result.normals_path.empty() && result.normals.size() == result.vertex_remap.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (!result.tangents_path.empty() && result.tangents.size() == result.vertex_remap.size()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        }
        if (!result.tangent_signs_path.empty() && result.tangent_signs.size() == result.vertex_remap.size()) {
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
        }
        const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
        if (!result.bone_counts_path.empty()
            && !result.bone_indices_path.empty()
            && !result.bone_weights_path.empty()
            && bone_counts.size() == result.vertex_remap.size()) {
            const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
            if (flat_bone_indices.size() == flat_bone_weights.size()) {
                write_int_binary_file(result.bone_counts_path, bone_counts);
                write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                out << ",\"bone_counts_binary\":";
                write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                out << ",\"bone_indices_binary\":";
                write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                out << ",\"bone_weights_binary\":";
                write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
            }
        }
        if (!result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertex_remap.size()) {
            write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
            out << ",\"source_vertex_map_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
        }
        if (!result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertex_remap.size()) {
            write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
            out << ",\"source_vertex_offsets_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string normals_report_json(const std::vector<SubmeshNormalsResult>& results, const std::string& operation) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, operation);
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshNormalsResult& result = results[i];
        out << "{\"index\":" << result.index;
        if (!result.normals_path.empty()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        } else {
            out << ",\"normals\":[";
            for (std::size_t j = 0; j < result.normals.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec3(out, result.normals[j]);
            }
            out << ']';
        }
        if (!result.faces.empty()) {
            if (!result.faces_path.empty()) {
                std::vector<int> flat_faces;
                flat_faces.reserve(result.faces.size() * 3);
                for (const std::array<int, 3>& face : result.faces) {
                    flat_faces.push_back(face[0]);
                    flat_faces.push_back(face[1]);
                    flat_faces.push_back(face[2]);
                }
                write_int_binary_file(result.faces_path, flat_faces);
                out << ",\"faces_binary\":";
                write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
            } else {
                out << ",\"faces\":[";
                for (std::size_t j = 0; j < result.faces.size(); ++j) {
                    if (j) {
                        out << ',';
                    }
                    out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
                }
                out << ']';
            }
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.changed_vertices.empty()) {
            if (operation != "flip_normals") {
                out << ",\"preview_vertex_update_group\":";
                std::vector<Vec3> changed_positions;
                changed_positions.reserve(result.changed_vertices.size());
                for (const int vertex_index : result.changed_vertices) {
                    if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= result.vertices.size()) {
                        changed_positions.clear();
                        break;
                    }
                    changed_positions.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                }
                if (!result.preview_vertex_path.empty() && changed_positions.size() == result.changed_vertices.size()) {
                    write_vec3_binary_file(result.preview_vertex_path, changed_positions);
                    write_sparse_preview_vertex_update_group(
                        out,
                        result.index,
                        result.changed_vertices,
                        changed_positions,
                        result.normals,
                        result.uvs,
                        result.preview_vertex_path,
                        changed_vertex_start,
                        result.source_vertex_map
                    );
                } else {
                    write_preview_vertex_update_group(
                        out,
                        result.index,
                        result.changed_vertices,
                        result.vertices,
                        result.normals,
                        result.uvs,
                        result.changed_vertices_path,
                        result.source_vertex_map
                    );
                }
            }
        }
        if (operation == "flip_normals" && !result.vertices.empty() && !result.faces.empty()) {
            out << ",\"preview_triangle_group\":";
            write_preview_triangle_group(
                out,
                result.index,
                result.vertices,
                result.faces,
                result.normals,
                result.uvs,
                result.preview_triangle_path,
                result.source_vertex_map
            );
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string tangents_report_json(const std::vector<SubmeshTangentsResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"generate_tangents\",\"tangent_backend\":";
    write_escaped(out, tangent_backend_summary(results));
    out << ",\"remap\":\"vertex_average_after_face_corner_output\",\"face_corner_remap\":\"face_corner_tangents_reported_vertex_storage_averaged\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshTangentsResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"tangent_backend\":";
        write_escaped(out, result.tangent_backend);
        out << ",\"face_corner_remap\":\"mikktspace_face_corner_tangents_reported_vertex_storage_averaged\""
            << ",\"face_corner_tangent_count\":" << result.face_corner_tangent_count
            << ",\"degenerate_uv_faces\":" << result.degenerate_uv_faces
            << ",\"vertex_storage_safe\":" << (result.vertex_storage_safe ? "true" : "false")
            << ",\"split_required_vertices\":[";
        for (std::size_t j = 0; j < result.split_required_vertices.size(); ++j) {
            if (j) {
                out << ',';
            }
            out << result.split_required_vertices[j];
        }
        out << ']';
        if (result.clear_tangents) {
            out << ",\"clear_tangents\":true";
            int changed_vertex_start = -1;
            write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
            out << "}";
            continue;
        }
        if (result.topology_split_applied) {
            out << ",\"topology_split_applied\":true"
                << ",\"output_vertex_count\":" << result.vertices.size()
                << ",\"output_face_count\":" << result.faces.size();
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
            write_faces_binary_file(result.faces_path, result.faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
            const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
            if (!result.bone_counts_path.empty()
                && !result.bone_indices_path.empty()
                && !result.bone_weights_path.empty()
                && bone_counts.size() == result.vertices.size()) {
                const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
                const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
                if (flat_bone_indices.size() == flat_bone_weights.size()) {
                    write_int_binary_file(result.bone_counts_path, bone_counts);
                    write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                    write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                    out << ",\"bone_counts_binary\":";
                    write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                    out << ",\"bone_indices_binary\":";
                    write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                    out << ",\"bone_weights_binary\":";
                    write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
                }
            }
            if (!result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertices.size()) {
                write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
                out << ",\"source_vertex_map_binary\":";
                write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
            }
            if (!result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertices.size()) {
                write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
                out << ",\"source_vertex_offsets_binary\":";
                write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
            }
        }
        if (!result.vertex_storage_safe && !result.topology_split_applied) {
            out << ",\"face_corner_tangents\":[";
            for (std::size_t j = 0; j < result.face_corner_tangents.size(); ++j) {
                if (j) {
                    out << ',';
                }
                const FaceCornerTangents& face_corners = result.face_corner_tangents[j];
                out << "{\"face_index\":" << face_corners.face_index << ",\"vertices\":[";
                for (std::size_t k = 0; k < face_corners.vertices.size(); ++k) {
                    if (k) {
                        out << ',';
                    }
                    out << face_corners.vertices[k];
                }
                out << "],\"tangents\":[";
                for (std::size_t k = 0; k < face_corners.tangents.size(); ++k) {
                    if (k) {
                        out << ',';
                    }
                    write_vec3(out, face_corners.tangents[k]);
                }
                out << "],\"signs\":[";
                for (std::size_t k = 0; k < face_corners.signs.size(); ++k) {
                    if (k) {
                        out << ',';
                    }
                    out << face_corners.signs[k];
                }
                out << "]}";
            }
            out << ']';
        }
        if (!result.tangents_path.empty()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        } else {
            out << ",\"tangents\":[";
            for (std::size_t j = 0; j < result.tangents.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec3(out, result.tangents[j]);
            }
            out << ']';
        }
        if (!result.topology_split_applied) {
            if (!result.tangent_signs_path.empty()) {
                write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
                out << ",\"tangent_signs_binary\":";
                write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
            } else {
                out << ",\"tangent_signs\":[";
                for (std::size_t j = 0; j < result.tangent_signs.size(); ++j) {
                    if (j) {
                        out << ',';
                    }
                    out << result.tangent_signs[j];
                }
                out << ']';
            }
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        out << "}";
    }
    out << "]}";
    return out.str();
}
