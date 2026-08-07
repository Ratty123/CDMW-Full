std::set<int> mesh_editor_clipboard_face_offsets(
    const MeshEditorSession& session,
    int submesh_index,
    const MeshSessionSubmesh& submesh,
    const std::string& target
) {
    std::set<int> selected;
    if (session.selection.source_indices.find(submesh_index) != session.selection.source_indices.end()) {
        for (std::size_t index = 0; index < submesh.faces.size(); ++index) {
            selected.insert(static_cast<int>(index));
        }
        return selected;
    }

    if (target == "face") {
        const auto found = session.selection.faces.find(submesh_index);
        if (found == session.selection.faces.end()) return selected;
        const std::vector<int> source_faces = submesh.source_face_indices.size() == submesh.faces.size()
            ? submesh.source_face_indices
            : identity_indices(submesh.faces.size());
        return compact_face_offsets_from_selection_values(found->second, source_faces, submesh.faces.size());
    }

    if (target == "edge") {
        const auto found = session.selection.edges.find(submesh_index);
        if (found == session.selection.edges.end()) return selected;
        for (std::size_t face_index = 0; face_index < submesh.faces.size(); ++face_index) {
            const std::array<int, 3>& face = submesh.faces[face_index];
            if (found->second.find(edge_key(face[0], face[1])) != found->second.end()
                && found->second.find(edge_key(face[1], face[2])) != found->second.end()
                && found->second.find(edge_key(face[2], face[0])) != found->second.end()) {
                selected.insert(static_cast<int>(face_index));
            }
        }
        return selected;
    }

    const auto found = session.selection.vertices.find(submesh_index);
    if (found == session.selection.vertices.end()) return selected;
    for (std::size_t face_index = 0; face_index < submesh.faces.size(); ++face_index) {
        const std::array<int, 3>& face = submesh.faces[face_index];
        if (found->second.find(face[0]) != found->second.end()
            && found->second.find(face[1]) != found->second.end()
            && found->second.find(face[2]) != found->second.end()) {
            selected.insert(static_cast<int>(face_index));
        }
    }
    return selected;
}

template <typename T>
std::vector<T> mesh_editor_clipboard_copy_vertex_channel(
    const std::vector<T>& source,
    const std::vector<int>& source_vertex_indices,
    std::size_t source_vertex_count
) {
    if (source.size() != source_vertex_count) return {};
    std::vector<T> copied;
    copied.reserve(source_vertex_indices.size());
    for (const int source_index : source_vertex_indices) {
        if (source_index < 0 || static_cast<std::size_t>(source_index) >= source.size()) return {};
        copied.push_back(source[static_cast<std::size_t>(source_index)]);
    }
    return copied;
}

MeshSessionSubmesh mesh_editor_clipboard_fragment(
    const MeshSessionSubmesh& source,
    const std::set<int>& selected_faces
) {
    MeshSessionSubmesh copied;
    copied.name = source.name;
    copied.material = source.material;
    copied.texture = source.texture;
    copied.extra_attrs = source.extra_attrs;

    std::set<int> used_vertices;
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= source.faces.size()) continue;
        const std::array<int, 3>& face = source.faces[static_cast<std::size_t>(face_index)];
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    if (used_vertices.empty()) return {};

    std::map<int, int> remap;
    std::vector<int> source_vertex_indices;
    source_vertex_indices.reserve(used_vertices.size());
    copied.vertices.reserve(used_vertices.size());
    for (const int source_index : used_vertices) {
        if (source_index < 0 || static_cast<std::size_t>(source_index) >= source.vertices.size()) return {};
        remap[source_index] = static_cast<int>(copied.vertices.size());
        source_vertex_indices.push_back(source_index);
        copied.vertices.push_back(source.vertices[static_cast<std::size_t>(source_index)]);
    }

    copied.faces.reserve(selected_faces.size());
    copied.source_face_indices.reserve(selected_faces.size());
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= source.faces.size()) continue;
        const std::array<int, 3>& face = source.faces[static_cast<std::size_t>(face_index)];
        const auto a = remap.find(face[0]);
        const auto b = remap.find(face[1]);
        const auto c = remap.find(face[2]);
        if (a == remap.end() || b == remap.end() || c == remap.end()) return {};
        copied.faces.push_back({a->second, b->second, c->second});
        copied.source_face_indices.push_back(
            source.source_face_indices.size() == source.faces.size()
                ? source.source_face_indices[static_cast<std::size_t>(face_index)]
                : face_index
        );
    }
    if (copied.faces.empty()) return {};

    const std::size_t source_vertex_count = source.vertices.size();
    copied.normals = mesh_editor_clipboard_copy_vertex_channel(source.normals, source_vertex_indices, source_vertex_count);
    copied.uvs = mesh_editor_clipboard_copy_vertex_channel(source.uvs, source_vertex_indices, source_vertex_count);
    copied.tangents = mesh_editor_clipboard_copy_vertex_channel(source.tangents, source_vertex_indices, source_vertex_count);
    copied.tangent_signs = mesh_editor_clipboard_copy_vertex_channel(source.tangent_signs, source_vertex_indices, source_vertex_count);
    copied.bone_indices = mesh_editor_clipboard_copy_vertex_channel(source.bone_indices, source_vertex_indices, source_vertex_count);
    copied.bone_weights = mesh_editor_clipboard_copy_vertex_channel(source.bone_weights, source_vertex_indices, source_vertex_count);
    copied.source_vertex_map = mesh_editor_clipboard_copy_vertex_channel(source.source_vertex_map, source_vertex_indices, source_vertex_count);
    copied.source_vertex_offsets = mesh_editor_clipboard_copy_vertex_channel(source.source_vertex_offsets, source_vertex_indices, source_vertex_count);
    return copied;
}

std::string mesh_editor_copy_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (session.active_stroke.active) {
        throw std::runtime_error("finish the active stroke before copying selection");
    }
    std::string target = lower_ascii(string_or(root.get("target"), "vertex"));
    if (target == "vertices") target = "vertex";
    if (target == "wires" || target == "wire" || target == "edges") target = "edge";
    if (target == "faces") target = "face";
    if (target != "vertex" && target != "edge" && target != "face") {
        throw std::runtime_error("unsupported clipboard selection target");
    }

    std::vector<MeshEditorClipboardFragment> clipboard;
    std::size_t copied_faces = 0;
    for (const auto& item : mesh_editor_submeshes(session)) {
        const std::set<int> face_offsets = mesh_editor_clipboard_face_offsets(
            session, item.first, item.second, target
        );
        if (face_offsets.empty()) continue;
        MeshSessionSubmesh fragment = mesh_editor_clipboard_fragment(item.second, face_offsets);
        if (fragment.faces.empty()) continue;
        copied_faces += fragment.faces.size();
        clipboard.push_back(MeshEditorClipboardFragment{item.first, std::move(fragment)});
    }
    if (clipboard.empty()) {
        throw std::runtime_error("No complete faces selected to copy");
    }
    session.clipboard = std::move(clipboard);

    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"copy\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"clipboard_fragment_count\":" << session.clipboard.size()
        << ",\"clipboard_face_count\":" << copied_faces << ',';
    mesh_editor_write_metrics(out, cpp_ms);
    out << '}';
    return out.str();
}

std::vector<SubmeshMeshEditResult> mesh_editor_paste_results(
    const MeshEditorSession& session,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    if (session.clipboard.empty()) {
        throw std::runtime_error("Mesh Editor clipboard is empty");
    }
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(session.clipboard.size());
    for (const MeshEditorClipboardFragment& fragment : session.clipboard) {
        const MeshSessionSubmesh& pasted = fragment.submesh;
        SubmeshMeshEditResult result;
        result.index = fragment.source_index;
        result.source_index = fragment.source_index;
        result.action = "paste";
        result.append_submesh = true;
        result.name_suffix = " selection copy";
        result.name = (pasted.name.empty()
            ? std::string("part_") + std::to_string(fragment.source_index)
            : pasted.name) + result.name_suffix;
        result.material = pasted.material;
        result.texture = pasted.texture;
        result.extra_attrs = pasted.extra_attrs;
        result.material_metadata_changed = true;
        result.vertices = pasted.vertices;
        result.faces = pasted.faces;
        result.source_face_indices = pasted.source_face_indices;
        result.normals = pasted.normals;
        result.preview_uvs = pasted.uvs;
        result.tangents = pasted.tangents;
        result.tangent_signs = pasted.tangent_signs;
        result.bones.indices = pasted.bone_indices;
        result.bones.weights = pasted.bone_weights;
        result.source_vertex_map = pasted.source_vertex_map;
        result.source_vertex_offsets = pasted.source_vertex_offsets;
        result.added_vertices = static_cast<int>(pasted.vertices.size());
        result.added_faces = static_cast<int>(pasted.faces.size());
        result.topology_changed = true;
        result.suppress_vertex_remap_report = true;
        mesh_editor_set_result_output_paths(result, delta_output_dir, session_id);
        results.push_back(std::move(result));
    }
    return results;
}
