bool preview_uv_wrap_repeat(const std::vector<Vec2>& uvs) {
    if (uvs.empty()) return false;
    double min_u = uvs[0][0];
    double max_u = uvs[0][0];
    double min_v = uvs[0][1];
    double max_v = uvs[0][1];
    for (const Vec2& uv : uvs) {
        min_u = std::min(min_u, uv[0]);
        max_u = std::max(max_u, uv[0]);
        min_v = std::min(min_v, uv[1]);
        max_v = std::max(max_v, uv[1]);
    }
    return min_u < -0.05 || max_u > 1.05 || min_v < -0.05 || max_v > 1.05;
}

void write_preview_geometry_outputs(
    const JsonValue& root,
    const std::string& output_path,
    const std::string& identity_output_path,
    const std::vector<char>& geometry,
    const std::vector<char>& identity
) {
    const bool append = bool_or(root.get("append"), false);
    write_binary_file(output_path, geometry, append);
    if (!identity_output_path.empty()) {
        write_binary_file(identity_output_path, identity, append);
    }
}

std::string run_preview_geometry(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    const std::string identity_output_path = string_or(root.get("identity_output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("preview geometry output_path is required");
    }
    const JsonValue* meshes = root.get("meshes");
    if (meshes == nullptr || meshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing meshes array");
    }
    std::vector<char> geometry;
    std::vector<char> identity;
    std::vector<PreviewGeometryBatchReport> batch_reports;
    int total_vertices = 0;
    for (const JsonValue& item : meshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int mesh_index = int_or(item.get("index"), -1);
        const std::vector<Vec3> positions = item_has_direct_geometry(item, "positions_binary", "positions")
            ? vertices_from_binary_or_json(item, "positions_binary", "positions")
            : mesh_vertices_from_item(item);
        if (mesh_index < 0 || positions.empty()) {
            continue;
        }
        PreviewTriangleIndexStream triangle_stream = preview_triangle_index_stream_from_binary_or_json(item, positions.size());
        std::vector<std::array<int, 3>> faces;
        if (triangle_stream.flat_indices.empty()) {
            faces = mesh_faces_from_item(item, positions.size());
            triangle_stream = preview_triangle_index_stream_from_faces(faces);
        }
        const std::vector<int>& flat_indices = triangle_stream.flat_indices;
        if (flat_indices.empty()) {
            continue;
        }
        const int source_submesh_index = int_or(item.get("source_submesh_index"), -1);
        const std::vector<int> source_vertices = mesh_source_vertex_indices_from_item(item, positions.size());
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(
            item,
            faces.empty() ? triangle_stream.face_ordinals.size() : faces.size());
        std::vector<Vec3> normals = mesh_normals_from_item(item);
        int normal_repair_count = 0;
        if (normals.size() != positions.size()) {
            normals.assign(positions.size(), {0.0, 0.0, 1.0});
            normal_repair_count = static_cast<int>(positions.size());
        } else {
            for (Vec3& normal : normals) {
                bool repaired = false;
                normal = sanitize_normal_for_preview(normal, &repaired);
                if (repaired) {
                    ++normal_repair_count;
                }
            }
        }
        std::vector<Vec2> uvs = item_has_direct_geometry(item, "texture_coordinates_binary", "texture_coordinates")
            ? uvs_from_binary_or_json(item, "texture_coordinates_binary", "texture_coordinates")
            : mesh_uvs_from_item(item);
        const bool has_uvs = uvs.size() == positions.size();
        if (!has_uvs) {
            uvs.assign(positions.size(), {0.0, 0.0});
        }
        const bool texture_wrap_repeat = has_uvs && preview_uv_wrap_repeat(uvs);
        const Vec3 color = vec3_or(item.get("color"), {1.0, 1.0, 1.0});
        const PreviewSmoothNormalsResult smooth = build_preview_smoothed_normals(positions, normals, flat_indices);
        const PreviewTangentFrames tangents = build_preview_tangent_frames(positions, uvs, normals, flat_indices);
        PreviewGeometryBatchReport report;
        report.mesh_index = mesh_index;
        report.first_vertex = total_vertices;
        report.vertex_count = static_cast<int>(flat_indices.size());
        report.base_color = color;
        report.has_texture_coordinates = has_uvs;
        report.texture_wrap_repeat = texture_wrap_repeat;
        const double vertex_total = static_cast<double>(std::max<std::size_t>(1, positions.size()));
        report.normal_repair_count = normal_repair_count;
        report.normal_finite_ratio = std::max(0.0, 1.0 - (static_cast<double>(normal_repair_count) / vertex_total));
        report.tangent_finite_ratio = std::max(0.0, 1.0 - (static_cast<double>(count_false_values(tangents.tangent_valid)) / vertex_total));
        report.bitangent_finite_ratio = std::max(0.0, 1.0 - (static_cast<double>(count_false_values(tangents.bitangent_valid)) / vertex_total));
        report.uv_finite_ratio = has_uvs ? 1.0 : 0.0;
        report.smooth_normal_ratio = smooth.changed_ratio;
        report.position_y_min = positions[0][1];
        report.position_y_max = positions[0][1];
        for (const Vec3& position : positions) {
            report.position_y_min = std::min(report.position_y_min, position[1]);
            report.position_y_max = std::max(report.position_y_max, position[1]);
        }
        report.bounds_min = positions[static_cast<std::size_t>(flat_indices[0])];
        report.bounds_max = report.bounds_min;
        for (int vertex_index : flat_indices) {
            const Vec3& position = positions[static_cast<std::size_t>(vertex_index)];
            report.bounds_min[0] = std::min(report.bounds_min[0], position[0]);
            report.bounds_min[1] = std::min(report.bounds_min[1], position[1]);
            report.bounds_min[2] = std::min(report.bounds_min[2], position[2]);
            report.bounds_max[0] = std::max(report.bounds_max[0], position[0]);
            report.bounds_max[1] = std::max(report.bounds_max[1], position[1]);
            report.bounds_max[2] = std::max(report.bounds_max[2], position[2]);
        }
        int tangent_checked = 0;
        int tangent_valid = 0;
        const int identity_offset = static_cast<int>(identity.size());
        report.source_vertex_indices.reserve(flat_indices.size());
        report.source_face_indices.reserve(flat_indices.size() / 3);
        for (std::size_t emitted = 0; emitted < flat_indices.size(); ++emitted) {
            const int vertex_index = flat_indices[emitted];
            const std::size_t source = static_cast<std::size_t>(vertex_index);
            const std::size_t face_output_index = emitted / 3;
            const int face_ordinal = face_output_index < triangle_stream.face_ordinals.size()
                ? triangle_stream.face_ordinals[face_output_index]
                : static_cast<int>(face_output_index);
            const int source_vertex_index = source < source_vertices.size()
                ? source_vertices[source]
                : vertex_index;
            const int source_face_index = face_ordinal >= 0 && static_cast<std::size_t>(face_ordinal) < source_faces.size()
                ? source_faces[static_cast<std::size_t>(face_ordinal)]
                : face_ordinal;
            report.source_vertex_indices.push_back(source_vertex_index);
            if (emitted % 3 == 0) {
                report.source_face_indices.push_back(source_face_index);
            }
            if (!identity_output_path.empty()) {
                append_i32_le(identity, source_submesh_index);
                append_i32_le(identity, source_vertex_index);
                append_i32_le(identity, source_face_index);
            }
            const Vec3 barycentric = (emitted % 3 == 0)
                ? Vec3{1.0, 0.0, 0.0}
                : ((emitted % 3 == 1) ? Vec3{0.0, 1.0, 0.0} : Vec3{0.0, 0.0, 1.0});
            append_preview_vertex(
                geometry,
                positions[source],
                normals[source],
                color,
                uvs[source],
                tangents.tangents[source],
                tangents.bitangents[source],
                smooth.normals[source],
                barycentric);
            ++tangent_checked;
            if (preview_vertex_tangent_usable(normals[source], uvs[source], tangents.tangents[source], tangents.bitangents[source])) {
                ++tangent_valid;
            }
        }
        report.tangents_usable = tangent_checked > 0 && (static_cast<double>(tangent_valid) / static_cast<double>(tangent_checked)) >= 0.80;
        report.identity_offset = identity_offset;
        report.identity_size = static_cast<int>(identity.size()) - identity_offset;
        total_vertices += report.vertex_count;
        batch_reports.push_back(report);
    }
    write_preview_geometry_outputs(root, output_path, identity_output_path, geometry, identity);
    return preview_geometry_report_json(batch_reports, total_vertices, static_cast<int>(geometry.size()), output_path);
}

std::string preview_identity_report_json(
    int source_submesh_index,
    int source_vertex_count,
    int source_face_count,
    int identity_size,
    const std::string& role,
    const std::string& part_name,
    bool editable
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_identity\""
        << ",\"source_submesh_index\":" << source_submesh_index
        << ",\"source_vertex_count\":" << source_vertex_count
        << ",\"source_face_count\":" << source_face_count
        << ",\"identity_stride_bytes\":12"
        << ",\"identity_size\":" << identity_size
        << ",\"role\":";
    write_escaped(out, role);
    out << ",\"part_name\":";
    write_escaped(out, part_name);
    out << ",\"editable\":" << (editable ? "true" : "false")
        << "}";
    return out.str();
}

std::string run_preview_identity(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("preview identity output_path is required");
    }
    const int source_submesh_index = int_or(root.get("source_submesh_index"), -1);
    const int vertex_count = std::max(0, int_or(root.get("vertex_count"), 0));
    const int source_vertex_start = int_or(root.get("source_vertex_start"), -1);
    const int source_vertex_range_count = std::max(0, int_or(root.get("source_vertex_count"), 0));
    const bool source_vertex_range = source_vertex_start >= 0 && source_vertex_range_count > 0;
    const int source_face_start = int_or(root.get("source_face_start"), -1);
    const int source_face_range_count = std::max(0, int_or(root.get("source_face_count"), 0));
    const bool source_face_range = source_face_start >= 0 && source_face_range_count > 0;
    const std::vector<int> source_vertices = source_vertex_range
        ? std::vector<int>()
        : int_vector_from_binary_or_json(root, "source_vertex_indices_binary", "source_vertex_indices");
    const std::vector<int> source_faces = source_face_range
        ? std::vector<int>()
        : int_vector_from_binary_or_json(root, "source_face_indices_binary", "source_face_indices");
    const std::string role = string_or(root.get("role"), "");
    const std::string part_name = string_or(root.get("part_name"), "");
    const std::string role_key = lower_ascii(role);
    const bool reference_role = role_key.find("reference") != std::string::npos || role_key.find("original") != std::string::npos;
    const bool editable = bool_or(root.get("editable"), source_submesh_index >= 0) && !reference_role;
    std::vector<char> identity;
    identity.reserve(static_cast<std::size_t>(vertex_count) * 12u);
    int max_source_vertex = -1;
    int max_source_face = -1;
    for (int value : source_vertices) {
        max_source_vertex = std::max(max_source_vertex, value);
    }
    if (source_vertex_range) {
        max_source_vertex = std::max(max_source_vertex, source_vertex_start + source_vertex_range_count - 1);
    }
    for (int value : source_faces) {
        max_source_face = std::max(max_source_face, value);
    }
    if (source_face_range) {
        max_source_face = std::max(max_source_face, source_face_start + source_face_range_count - 1);
    }
    for (int vertex_offset = 0; vertex_offset < vertex_count; ++vertex_offset) {
        const int source_vertex_index = source_vertex_range && vertex_offset < source_vertex_range_count
            ? source_vertex_start + vertex_offset
            : vertex_offset < static_cast<int>(source_vertices.size())
            ? source_vertices[static_cast<std::size_t>(vertex_offset)]
            : vertex_offset;
        const int face_offset = vertex_offset / 3;
        const int source_face_index = source_face_range && face_offset < source_face_range_count
            ? source_face_start + face_offset
            : face_offset < static_cast<int>(source_faces.size())
            ? source_faces[static_cast<std::size_t>(face_offset)]
            : face_offset;
        append_i32_le(identity, source_submesh_index);
        append_i32_le(identity, source_vertex_index);
        append_i32_le(identity, source_face_index);
    }
    write_binary_file(output_path, identity, bool_or(root.get("append"), true));
    return preview_identity_report_json(
        source_submesh_index,
        max_source_vertex >= 0 ? max_source_vertex + 1 : 0,
        max_source_face >= 0 ? max_source_face + 1 : 0,
        static_cast<int>(identity.size()),
        role,
        part_name,
        editable);
}

MeshSessionSubmesh mesh_session_submesh_from_item(const JsonValue& item) {
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        MeshSessionSubmesh stored_submesh = *session;
        if (item.get("name") != nullptr || item.get("part_name") != nullptr) {
            stored_submesh.name = string_or(item.get("name"), string_or(item.get("part_name"), stored_submesh.name));
        }
        if (item.get("material") != nullptr) {
            stored_submesh.material = string_or(item.get("material"), stored_submesh.material);
        }
        if (item.get("texture") != nullptr) {
            stored_submesh.texture = string_or(item.get("texture"), stored_submesh.texture);
        }
        if (const JsonValue* extra_attrs = item.get("extra_attrs")) {
            if (extra_attrs->type == JsonValue::Type::Object) {
                stored_submesh.extra_attrs = *extra_attrs;
            }
        }
        return stored_submesh;
    }
    MeshSessionSubmesh stored_submesh;
    stored_submesh.name = string_or(item.get("name"), string_or(item.get("part_name"), ""));
    stored_submesh.material = string_or(item.get("material"), "");
    stored_submesh.texture = string_or(item.get("texture"), "");
    if (const JsonValue* extra_attrs = item.get("extra_attrs")) {
        if (extra_attrs->type == JsonValue::Type::Object) {
            stored_submesh.extra_attrs = *extra_attrs;
        }
    }
    stored_submesh.vertices = vertices_from_binary_or_json(item, "vertices_binary", "vertices");
    if (stored_submesh.vertices.empty()) {
        return stored_submesh;
    }
    stored_submesh.faces = faces_from_binary_or_json(item, stored_submesh.vertices.size());
    stored_submesh.source_face_indices = int_vector_from_binary_or_json(
        item,
        "source_face_indices_binary",
        "source_face_indices",
        "source_face_start",
        "source_face_count"
    );
    if (stored_submesh.source_face_indices.empty() && item.get("faces") != nullptr) {
        stored_submesh.source_face_indices = source_face_indices_from_faces_json(item.get("faces"), stored_submesh.vertices.size());
    }
    bool valid_source_faces = stored_submesh.source_face_indices.size() == stored_submesh.faces.size();
    for (const int source_face_index : stored_submesh.source_face_indices) {
        if (source_face_index < 0) {
            valid_source_faces = false;
            break;
        }
    }
    if (!valid_source_faces) {
        stored_submesh.source_face_indices = identity_indices(stored_submesh.faces.size());
    }
    stored_submesh.normals = vertices_from_binary_or_json(item, "normals_binary", "normals");
    if (stored_submesh.normals.size() != stored_submesh.vertices.size()) {
        stored_submesh.normals.clear();
    }
    stored_submesh.uvs = uvs_from_binary_or_json(item, "uvs_binary", "uvs");
    if (stored_submesh.uvs.size() != stored_submesh.vertices.size()) {
        stored_submesh.uvs.clear();
    }
    stored_submesh.tangents = vertices_from_binary_or_json(item, "tangents_binary", "tangents");
    if (stored_submesh.tangents.size() != stored_submesh.vertices.size()) {
        stored_submesh.tangents.clear();
    }
    stored_submesh.tangent_signs = double_vector_from_binary_or_json(item, "tangent_signs_binary", "tangent_signs");
    if (stored_submesh.tangent_signs.size() != stored_submesh.vertices.size()) {
        stored_submesh.tangent_signs.clear();
    }
    const BoneAssignments stored_bones = bone_assignments_from_binary(item);
    if (valid_bone_assignments(stored_bones) && stored_bones.indices.size() == stored_submesh.vertices.size()) {
        stored_submesh.bone_indices = stored_bones.indices;
        stored_submesh.bone_weights = stored_bones.weights;
    }
    stored_submesh.source_vertex_map = int_vector_from_binary_or_json(
        item,
        "source_vertex_map_binary",
        "source_vertex_map",
        "source_vertex_map_start",
        "source_vertex_map_count"
    );
    if (stored_submesh.source_vertex_map.size() != stored_submesh.vertices.size()) {
        stored_submesh.source_vertex_map.clear();
    }
    stored_submesh.source_vertex_offsets = source_vertex_offsets_from_item(item);
    if (stored_submesh.source_vertex_offsets.size() != stored_submesh.vertices.size()) {
        stored_submesh.source_vertex_offsets.clear();
    }
    return stored_submesh;
}

std::string run_mesh_session(const JsonValue& root) {
    const std::string session_id = string_or(root.get("session_id"), "");
    if (session_id.empty()) {
        throw std::runtime_error("missing mesh session_id");
    }
    std::string operation = string_or(root.get("operation"), "store");
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (operation == "clear") {
        g_mesh_sessions.erase(session_id);
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"mesh_session\",\"session_id\":";
        write_escaped(out, session_id);
        out << ",\"submesh_count\":0,\"vertex_count\":0,\"face_count\":0,\"native_session_count\":"
            << g_mesh_sessions.size() << "}";
        return out.str();
    }

    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing mesh session submeshes");
    }
    std::map<int, MeshSessionSubmesh>& session = g_mesh_sessions[session_id];
    int stored = 0;
    int vertex_count = 0;
    int face_count = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        MeshSessionSubmesh stored_submesh = mesh_session_submesh_from_item(item);
        if (stored_submesh.vertices.empty()) {
            continue;
        }
        vertex_count += static_cast<int>(stored_submesh.vertices.size());
        face_count += static_cast<int>(stored_submesh.faces.size());
        session[index] = std::move(stored_submesh);
        ++stored;
    }

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"mesh_session\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"submesh_count\":" << stored
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"native_session_count\":" << g_mesh_sessions.size() << "}";
    return out.str();
}

std::string mesh_editor_native_session_id(const std::string& session_id) {
    return "mesh-editor-session:" + session_id;
}
