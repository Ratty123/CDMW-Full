struct MeshSnapshotReportCounts {
    int submeshes = 0;
    int vertices = 0;
    int faces = 0;
};

std::string mesh_snapshot_clear_report(const std::string& snapshot_id) {
    if (!snapshot_id.empty()) {
        g_mesh_snapshots.erase(snapshot_id);
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"clear_snapshot\",\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << "}";
    return out.str();
}

std::string mesh_snapshot_restore_report(
    const JsonValue& root,
    const JsonValue& submeshes,
    const std::string& snapshot_id
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"restore_snapshot\"";
    if (!snapshot_id.empty()) {
        out << ",\"snapshot_id\":";
        write_escaped(out, snapshot_id);
    }
    out << ",\"submeshes\":[";
    bool wrote = false;
    MeshSnapshotReportCounts counts;
    for (const JsonValue& item : submeshes.array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        const std::string session_id = string_or(item.get("session_id"), "");
        const MeshSessionSubmesh* snapshot = mesh_snapshot_submesh_for_item(snapshot_id, item);
        if (index < 0 || session_id.empty() || snapshot == nullptr || snapshot->vertices.empty()) {
            continue;
        }
        g_mesh_sessions[session_id][index] = *snapshot;
        if (wrote) {
            out << ',';
        }
        wrote = true;
        ++counts.submeshes;
        counts.vertices += static_cast<int>(snapshot->vertices.size());
        counts.faces += static_cast<int>(snapshot->faces.size());
        out << "{\"index\":" << index << ",\"session_id\":";
        write_escaped(out, session_id);
        out << ",\"vertex_count\":" << snapshot->vertices.size()
            << ",\"face_count\":" << snapshot->faces.size() << "}";
    }
    out << "],\"restored_submesh_count\":" << counts.submeshes
        << ",\"vertex_count\":" << counts.vertices
        << ",\"face_count\":" << counts.faces << "}";
    return out.str();
}

void mesh_snapshot_write_source_faces(
    std::ostream& out,
    const JsonValue& item,
    const MeshSessionSubmesh& session
) {
    const std::string path = string_or(item.get("source_face_indices_output_path"), "");
    if (path.empty() || session.source_face_indices.size() != session.faces.size()) {
        return;
    }
    int start = -1;
    if (contiguous_int_range(session.source_face_indices, start)) {
        out << ",\"source_face_start\":" << start
            << ",\"source_face_count\":" << session.source_face_indices.size();
        return;
    }
    write_int_binary_file(path, session.source_face_indices);
    out << ",\"source_face_indices_binary\":";
    write_int_binary_descriptor(out, path, session.source_face_indices.size(), 1);
}

void mesh_snapshot_write_vertex_channels(
    std::ostream& out,
    const JsonValue& item,
    const MeshSessionSubmesh& session
) {
    const std::string normals_path = string_or(item.get("normals_output_path"), "");
    if (!normals_path.empty() && session.normals.size() == session.vertices.size()) {
        write_vec3_binary_file(normals_path, session.normals);
        out << ",\"normals_binary\":";
        write_vec3_binary_descriptor(out, normals_path, session.normals.size());
    }
    const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
    if (!uvs_path.empty() && session.uvs.size() == session.vertices.size()) {
        write_vec2_binary_file(uvs_path, session.uvs);
        out << ",\"uvs_binary\":";
        write_vec2_binary_descriptor(out, uvs_path, session.uvs.size());
    }
    const std::string tangents_path = string_or(item.get("tangents_output_path"), "");
    if (!tangents_path.empty() && session.tangents.size() == session.vertices.size()) {
        write_vec3_binary_file(tangents_path, session.tangents);
        out << ",\"tangents_binary\":";
        write_vec3_binary_descriptor(out, tangents_path, session.tangents.size());
    }
    const std::string signs_path = string_or(item.get("tangent_signs_output_path"), "");
    if (!signs_path.empty() && session.tangent_signs.size() == session.vertices.size()) {
        write_double_binary_file(signs_path, session.tangent_signs);
        out << ",\"tangent_signs_binary\":";
        write_f64_binary_descriptor(out, signs_path, session.tangent_signs.size());
    }
}

void mesh_snapshot_write_bones(
    std::ostream& out,
    const JsonValue& item,
    const MeshSessionSubmesh& session
) {
    const std::string counts_path = string_or(item.get("bone_counts_output_path"), "");
    const std::string indices_path = string_or(item.get("bone_indices_output_path"), "");
    const std::string weights_path = string_or(item.get("bone_weights_output_path"), "");
    const BoneAssignments bones{session.bone_indices, session.bone_weights};
    const std::vector<int> counts = bone_assignment_counts(bones);
    if (counts_path.empty() || indices_path.empty() || weights_path.empty()
        || !valid_bone_assignments(bones) || counts.size() != session.vertices.size()) {
        return;
    }
    const std::vector<int> indices = flatten_bone_indices(bones);
    const std::vector<double> weights = flatten_bone_weights(bones);
    if (indices.size() != weights.size()) {
        return;
    }
    write_int_binary_file(counts_path, counts);
    write_int_binary_file(indices_path, indices);
    write_double_binary_file(weights_path, weights);
    out << ",\"bone_counts_binary\":";
    write_int_binary_descriptor(out, counts_path, counts.size(), 1);
    out << ",\"bone_indices_binary\":";
    write_int_binary_descriptor(out, indices_path, indices.size(), 1);
    out << ",\"bone_weights_binary\":";
    write_f64_binary_descriptor(out, weights_path, weights.size());
}

void mesh_snapshot_write_source_vertex_maps(
    std::ostream& out,
    const JsonValue& item,
    const MeshSessionSubmesh& session
) {
    const std::string map_path = string_or(item.get("source_vertex_map_output_path"), "");
    if (!map_path.empty() && session.source_vertex_map.size() == session.vertices.size()) {
        int start = -1;
        if (contiguous_int_range(session.source_vertex_map, start)) {
            out << ",\"source_vertex_map_start\":" << start
                << ",\"source_vertex_map_count\":" << session.source_vertex_map.size();
        } else {
            write_int_binary_file(map_path, session.source_vertex_map);
            out << ",\"source_vertex_map_binary\":";
            write_int_binary_descriptor(out, map_path, session.source_vertex_map.size(), 1);
        }
    }
    const std::string offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
    if (offsets_path.empty() || session.source_vertex_offsets.size() != session.vertices.size()) {
        return;
    }
    int start = -1;
    int stride = 0;
    if (contiguous_int_stride_range(session.source_vertex_offsets, start, stride)) {
        out << ",\"source_vertex_offsets_start\":" << start
            << ",\"source_vertex_offsets_count\":" << session.source_vertex_offsets.size()
            << ",\"source_vertex_offsets_stride\":" << stride;
    } else {
        write_int_binary_file(offsets_path, session.source_vertex_offsets);
        out << ",\"source_vertex_offsets_binary\":";
        write_int_binary_descriptor(out, offsets_path, session.source_vertex_offsets.size(), 1);
    }
}

bool mesh_snapshot_write_export_item(
    std::ostream& out,
    const JsonValue& item,
    const std::string& snapshot_id,
    bool export_snapshot,
    MeshSnapshotReportCounts& counts
) {
    if (item.type != JsonValue::Type::Object) {
        return false;
    }
    const int index = int_or(item.get("index"), -1);
    const MeshSessionSubmesh* session = export_snapshot
        ? mesh_snapshot_submesh_for_item(snapshot_id, item)
        : mesh_session_submesh_for_item(item);
    if (index < 0 || session == nullptr || session->vertices.empty()) {
        return false;
    }
    if (!export_snapshot && !snapshot_id.empty()) {
        g_mesh_snapshots[snapshot_id][index] = *session;
    }
    const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
    const std::string faces_path = string_or(item.get("faces_output_path"), "");
    if (vertices_path.empty() || faces_path.empty()) {
        throw std::runtime_error("missing snapshot output paths");
    }
    write_vec3_binary_file(vertices_path, session->vertices);
    write_faces_binary_file(faces_path, session->faces);
    ++counts.submeshes;
    counts.vertices += static_cast<int>(session->vertices.size());
    counts.faces += static_cast<int>(session->faces.size());
    out << "{\"index\":" << index << ",\"session_id\":";
    write_escaped(out, string_or(item.get("session_id"), ""));
    out << ",\"vertex_count\":" << session->vertices.size()
        << ",\"face_count\":" << session->faces.size()
        << ",\"vertices_binary\":";
    write_vec3_binary_descriptor(out, vertices_path, session->vertices.size());
    out << ",\"faces_binary\":";
    write_int_binary_descriptor(out, faces_path, session->faces.size(), 3);
    mesh_snapshot_write_source_faces(out, item, *session);
    mesh_snapshot_write_vertex_channels(out, item, *session);
    mesh_snapshot_write_bones(out, item, *session);
    mesh_snapshot_write_source_vertex_maps(out, item, *session);
    out << "}";
    return true;
}

std::string mesh_snapshot_export_report(
    const JsonValue& submeshes,
    const std::string& snapshot_id,
    bool export_snapshot
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, export_snapshot ? "export_snapshot" : "snapshot_submeshes");
    if (!snapshot_id.empty()) {
        out << ",\"snapshot_id\":";
        write_escaped(out, snapshot_id);
    }
    out << ",\"submeshes\":[";
    bool wrote = false;
    MeshSnapshotReportCounts counts;
    for (const JsonValue& item : submeshes.array_value) {
        std::ostringstream item_out;
        if (!mesh_snapshot_write_export_item(item_out, item, snapshot_id, export_snapshot, counts)) {
            continue;
        }
        if (wrote) {
            out << ',';
        }
        wrote = true;
        out << item_out.str();
    }
    out << "]";
    if (!snapshot_id.empty()) {
        out << ",\"snapshot_handle\":{\"id\":";
        write_escaped(out, snapshot_id);
        out << ",\"submesh_count\":" << counts.submeshes
            << ",\"vertex_count\":" << counts.vertices
            << ",\"face_count\":" << counts.faces << "}";
    }
    out << "}";
    return out.str();
}

std::string snapshot_submeshes_report_json(const JsonValue& root) {
    std::string operation = string_or(root.get("operation"), "snapshot_submeshes");
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const std::string snapshot_id = string_or(root.get("snapshot_id"), "");
    if (operation == "clear_snapshot") {
        return mesh_snapshot_clear_report(snapshot_id);
    }
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    if (operation == "restore_snapshot") {
        return mesh_snapshot_restore_report(root, *submeshes, snapshot_id);
    }
    return mesh_snapshot_export_report(*submeshes, snapshot_id, operation == "export_snapshot");
}
