void mesh_editor_write_export_snapshot_submesh(
    std::ostream& exported_submeshes,
    bool& wrote_exported_submesh,
    const JsonValue& item,
    const std::string& session_id,
    const MeshEditorSession& session
) {
    if (item.type != JsonValue::Type::Object) {
        return;
    }
    const int index = int_or(item.get("index"), -1);
    const auto submesh_found = mesh_editor_submeshes(session).find(index);
    if (submesh_found == mesh_editor_submeshes(session).end()) {
        return;
    }
    const MeshSessionSubmesh& submesh = submesh_found->second;
    const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
    const std::string faces_path = string_or(item.get("faces_output_path"), "");
    if (vertices_path.empty() || faces_path.empty()) {
        const std::string normals_path = string_or(item.get("normals_output_path"), "");
        const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
        if (!vertices_path.empty()) write_vec3_binary_file(vertices_path, submesh.vertices);
        if (!faces_path.empty()) write_faces_binary_file(faces_path, submesh.faces);
        if (!normals_path.empty()) write_vec3_binary_file(normals_path, submesh.normals);
        if (!uvs_path.empty()) write_vec2_binary_file(uvs_path, submesh.uvs);
        return;
    }
    write_vec3_binary_file(vertices_path, submesh.vertices);
    write_faces_binary_file(faces_path, submesh.faces);
    if (wrote_exported_submesh) {
        exported_submeshes << ',';
    }
    wrote_exported_submesh = true;
    exported_submeshes << "{\"index\":" << index
        << ",\"session_id\":";
    write_escaped(exported_submeshes, session_id);
    exported_submeshes << ",\"name\":";
    write_escaped(exported_submeshes, submesh.name);
    exported_submeshes << ",\"material\":";
    write_escaped(exported_submeshes, submesh.material);
    exported_submeshes << ",\"texture\":";
    write_escaped(exported_submeshes, submesh.texture);
    mesh_editor_write_extra_attrs_field(exported_submeshes, submesh.extra_attrs);
    exported_submeshes << ",\"vertex_count\":" << submesh.vertices.size()
        << ",\"face_count\":" << submesh.faces.size()
        << ",\"vertices_binary\":";
    write_vec3_binary_descriptor(exported_submeshes, vertices_path, submesh.vertices.size());
    exported_submeshes << ",\"faces_binary\":";
    write_int_binary_descriptor(exported_submeshes, faces_path, submesh.faces.size(), 3);

    const std::string source_faces_path = string_or(item.get("source_face_indices_output_path"), "");
    if (!source_faces_path.empty() && submesh.source_face_indices.size() == submesh.faces.size()) {
        int source_face_start = -1;
        if (contiguous_int_range(submesh.source_face_indices, source_face_start)) {
            exported_submeshes << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << submesh.source_face_indices.size();
        } else {
            write_int_binary_file(source_faces_path, submesh.source_face_indices);
            exported_submeshes << ",\"source_face_indices_binary\":";
            write_int_binary_descriptor(exported_submeshes, source_faces_path, submesh.source_face_indices.size(), 1);
        }
    }
    const std::string normals_path = string_or(item.get("normals_output_path"), "");
    if (!normals_path.empty() && submesh.normals.size() == submesh.vertices.size()) {
        write_vec3_binary_file(normals_path, submesh.normals);
        exported_submeshes << ",\"normals_binary\":";
        write_vec3_binary_descriptor(exported_submeshes, normals_path, submesh.normals.size());
    }
    const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
    if (!uvs_path.empty() && submesh.uvs.size() == submesh.vertices.size()) {
        write_vec2_binary_file(uvs_path, submesh.uvs);
        exported_submeshes << ",\"uvs_binary\":";
        write_vec2_binary_descriptor(exported_submeshes, uvs_path, submesh.uvs.size());
    }
    const std::string tangents_path = string_or(item.get("tangents_output_path"), "");
    if (!tangents_path.empty() && submesh.tangents.size() == submesh.vertices.size()) {
        write_vec3_binary_file(tangents_path, submesh.tangents);
        exported_submeshes << ",\"tangents_binary\":";
        write_vec3_binary_descriptor(exported_submeshes, tangents_path, submesh.tangents.size());
    }
    const std::string tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
    if (!tangent_signs_path.empty() && submesh.tangent_signs.size() == submesh.vertices.size()) {
        write_double_binary_file(tangent_signs_path, submesh.tangent_signs);
        exported_submeshes << ",\"tangent_signs_binary\":";
        write_f64_binary_descriptor(exported_submeshes, tangent_signs_path, submesh.tangent_signs.size());
    }
    const std::string bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
    const std::string bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
    const std::string bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
    const BoneAssignments bones{submesh.bone_indices, submesh.bone_weights};
    const std::vector<int> bone_counts = bone_assignment_counts(bones);
    if (!bone_counts_path.empty()
        && !bone_indices_path.empty()
        && !bone_weights_path.empty()
        && valid_bone_assignments(bones)
        && bone_counts.size() == submesh.vertices.size()) {
        const std::vector<int> flat_bone_indices = flatten_bone_indices(bones);
        const std::vector<double> flat_bone_weights = flatten_bone_weights(bones);
        if (flat_bone_indices.size() == flat_bone_weights.size()) {
            write_int_binary_file(bone_counts_path, bone_counts);
            write_int_binary_file(bone_indices_path, flat_bone_indices);
            write_double_binary_file(bone_weights_path, flat_bone_weights);
            exported_submeshes << ",\"bone_counts_binary\":";
            write_int_binary_descriptor(exported_submeshes, bone_counts_path, bone_counts.size(), 1);
            exported_submeshes << ",\"bone_indices_binary\":";
            write_int_binary_descriptor(exported_submeshes, bone_indices_path, flat_bone_indices.size(), 1);
            exported_submeshes << ",\"bone_weights_binary\":";
            write_f64_binary_descriptor(exported_submeshes, bone_weights_path, flat_bone_weights.size());
        }
    }
    const std::string source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
    if (!source_vertex_map_path.empty() && submesh.source_vertex_map.size() == submesh.vertices.size()) {
        int source_vertex_map_start = -1;
        if (contiguous_int_range(submesh.source_vertex_map, source_vertex_map_start)) {
            exported_submeshes << ",\"source_vertex_map_start\":" << source_vertex_map_start
                << ",\"source_vertex_map_count\":" << submesh.source_vertex_map.size();
        } else {
            write_int_binary_file(source_vertex_map_path, submesh.source_vertex_map);
            exported_submeshes << ",\"source_vertex_map_binary\":";
            write_int_binary_descriptor(exported_submeshes, source_vertex_map_path, submesh.source_vertex_map.size(), 1);
        }
    }
    const std::string source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
    if (!source_vertex_offsets_path.empty() && submesh.source_vertex_offsets.size() == submesh.vertices.size()) {
        int source_vertex_offsets_start = -1;
        int source_vertex_offsets_stride = 0;
        if (contiguous_int_stride_range(submesh.source_vertex_offsets, source_vertex_offsets_start, source_vertex_offsets_stride)) {
            exported_submeshes << ",\"source_vertex_offsets_start\":" << source_vertex_offsets_start
                << ",\"source_vertex_offsets_count\":" << submesh.source_vertex_offsets.size()
                << ",\"source_vertex_offsets_stride\":" << source_vertex_offsets_stride;
        } else {
            write_int_binary_file(source_vertex_offsets_path, submesh.source_vertex_offsets);
            exported_submeshes << ",\"source_vertex_offsets_binary\":";
            write_int_binary_descriptor(exported_submeshes, source_vertex_offsets_path, submesh.source_vertex_offsets.size(), 1);
        }
    }
    exported_submeshes << '}';
}

std::string mesh_editor_export_snapshot_report(
    const JsonValue& root,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const JsonValue* requested = root.get("submeshes");
    std::ostringstream exported_submeshes;
    bool wrote_exported_submesh = false;
    if (requested != nullptr && requested->type == JsonValue::Type::Array) {
        for (const JsonValue& item : requested->array_value) {
            mesh_editor_write_export_snapshot_submesh(
                exported_submeshes,
                wrote_exported_submesh,
                item,
                session_id,
                session
            );
        }
    }
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"export_snapshot\",\"session_id\":";
    write_escaped(out, session_id);
    out << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    if (requested != nullptr && requested->type == JsonValue::Type::Array) {
        out << "\"submeshes\":[" << exported_submeshes.str() << ']';
    } else {
        mesh_editor_write_submesh_summaries(out, session);
    }
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}
