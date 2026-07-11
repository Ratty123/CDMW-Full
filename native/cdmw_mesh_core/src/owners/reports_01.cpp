void write_full_preview_vertex_update_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<Vec3>& vertices,
    const std::vector<Vec3>& normals,
    const std::vector<Vec2>& uvs,
    const std::string& positions_path,
    const std::vector<int>& source_vertex_map = std::vector<int>()
) {
    const std::size_t count = vertices.size();
    const std::vector<int> identity = identity_indices(count);
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << submesh_index;
    write_preview_source_vertex_ids(
        out,
        source_vertex_map.size() == count ? source_vertex_map : identity,
        positions_path.empty() ? std::string() : sibling_binary_path(positions_path, ".source_indices.bin")
    );
    if (!positions_path.empty()) {
        write_vec3_binary_file(positions_path, vertices);
        out << ",\"positions_binary\":";
        write_preview_binary_descriptor(out, positions_path, count, 3, "f64");
        if (normals.size() == count) {
            const std::string normals_path = sibling_binary_path(positions_path, ".normals.bin");
            write_vec3_binary_file(normals_path, normals);
            out << ",\"normals_binary\":";
            write_preview_binary_descriptor(out, normals_path, count, 3, "f64");
        }
        if (uvs.size() == count) {
            const std::string uvs_path = sibling_binary_path(positions_path, ".uvs.bin");
            write_vec2_binary_file(uvs_path, uvs);
            out << ",\"uvs_binary\":";
            write_preview_binary_descriptor(out, uvs_path, count, 2, "f64");
        }
        out << "}";
        return;
    }
    out << ",\"positions\":[";
    write_flat_vec3_for_indices(out, vertices, identity_indices(count));
    out << "],\"normals\":[";
    if (normals.size() == count) {
        write_flat_vec3_for_indices(out, normals, identity_indices(count));
    }
    out << "],\"uvs\":[";
    if (uvs.size() == count) {
        write_flat_vec2_for_indices(out, uvs, identity_indices(count));
    }
    out << "]}";
}

void write_preview_triangle_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<Vec3>& normals,
    const std::vector<Vec2>& uvs,
    const std::string& preview_triangle_path = std::string(),
    const std::vector<int>& source_vertex_indices = std::vector<int>(),
    const std::vector<int>& source_face_indices = std::vector<int>()
) {
    const bool has_triangles = !vertices.empty() && !faces.empty();
    const std::vector<int> preview_source_vertex_indices = source_vertex_indices.size() == vertices.size()
        ? source_vertex_indices
        : identity_indices(vertices.size());
    const std::vector<int> preview_source_face_indices = source_face_indices.size() == faces.size()
        ? source_face_indices
        : identity_indices(faces.size());
    out << "{\"preview_backend\":\"cdmw_mesh_core\""
        << ",\"source_submesh_index\":" << submesh_index;
    if (has_triangles && !preview_triangle_path.empty()) {
        std::vector<int> indices;
        indices.reserve(faces.size() * 3u);
        for (const std::array<int, 3>& face : faces) {
            indices.push_back(face[0]);
            indices.push_back(face[1]);
            indices.push_back(face[2]);
        }
        const std::string normals_path = sibling_binary_path(preview_triangle_path, ".normals.bin");
        const std::string uvs_path = sibling_binary_path(preview_triangle_path, ".uvs.bin");
        const std::string indices_path = sibling_binary_path(preview_triangle_path, ".indices.bin");
        write_vec3_binary_file(preview_triangle_path, vertices);
        if (uvs.size() == vertices.size()) {
            write_vec2_binary_file(uvs_path, uvs);
        }
        if (normals.size() == vertices.size()) {
            write_vec3_binary_file(normals_path, normals);
        }
        write_int_binary_file(indices_path, indices);
        int source_vertex_start = -1;
        if (contiguous_int_range(preview_source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << preview_source_vertex_indices.size();
        } else {
            const std::string source_vertices_path = sibling_binary_path(preview_triangle_path, ".source_vertices.bin");
            write_int_binary_file(source_vertices_path, preview_source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_preview_binary_descriptor(out, source_vertices_path, preview_source_vertex_indices.size(), 1, "i32");
        }
        int source_face_start = -1;
        if (contiguous_int_range(preview_source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << preview_source_face_indices.size();
        } else {
            const std::string source_faces_path = sibling_binary_path(preview_triangle_path, ".source_faces.bin");
            write_int_binary_file(source_faces_path, preview_source_face_indices);
            out << ",\"source_face_indices_binary\":";
            write_preview_binary_descriptor(out, source_faces_path, preview_source_face_indices.size(), 1, "i32");
        }
        out << ",\"positions_binary\":";
        write_preview_binary_descriptor(out, preview_triangle_path, vertices.size(), 3, "f64");
        if (normals.size() == vertices.size()) {
            out << ",\"normals_binary\":";
            write_preview_binary_descriptor(out, normals_path, normals.size(), 3, "f64");
        }
        if (uvs.size() == vertices.size()) {
            out << ",\"uvs_binary\":";
            write_preview_binary_descriptor(out, uvs_path, uvs.size(), 2, "f64");
        }
        out << ",\"indices_binary\":";
        write_preview_binary_descriptor(out, indices_path, indices.size(), 1, "i32");
        out << '}';
        return;
    }
    int source_vertex_start = -1;
    if (has_triangles && contiguous_int_range(preview_source_vertex_indices, source_vertex_start)) {
        out << ",\"source_vertex_start\":" << source_vertex_start
            << ",\"source_vertex_count\":" << preview_source_vertex_indices.size();
    } else {
        out << ",\"source_vertex_indices\":[";
        if (has_triangles) {
            for (std::size_t j = 0; j < vertices.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                out << preview_source_vertex_indices[j];
            }
        }
        out << ']';
    }
    int source_face_start = -1;
    if (has_triangles && contiguous_int_range(preview_source_face_indices, source_face_start)) {
        out << ",\"source_face_start\":" << source_face_start
            << ",\"source_face_count\":" << preview_source_face_indices.size();
    } else {
        out << ",\"source_face_indices\":[";
        for (std::size_t j = 0; j < faces.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << preview_source_face_indices[j];
        }
        out << ']';
    }
    out << ",\"positions\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < vertices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << std::setprecision(17) << vertices[j][0] << ',' << vertices[j][1] << ',' << vertices[j][2];
        }
    }
    out << "],\"normals\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < normals.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << std::setprecision(17) << normals[j][0] << ',' << normals[j][1] << ',' << normals[j][2];
        }
    }
    out << "],\"uvs\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < uvs.size() && j < vertices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << std::setprecision(17) << uvs[j][0] << ',' << uvs[j][1];
        }
    }
    out << "],\"indices\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < faces.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << faces[j][0] << ',' << faces[j][1] << ',' << faces[j][2];
        }
    }
    out << "]}";
}

std::string preview_triangle_groups_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_triangle_groups\",\"groups\":[";
    bool first = true;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("source_submesh_index"), int_or(item.get("index"), -1));
        if (submesh_index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        std::vector<Vec3> normals = mesh_normals_from_item(item);
        if (normals.size() != vertices.size() && !vertices.empty() && !faces.empty()) {
            normals = compute_smooth_normals(vertices, faces);
        }
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (uvs.size() > vertices.size()) {
            uvs.resize(vertices.size());
        }
        const std::vector<int> source_vertices = mesh_source_vertex_indices_from_item(item, vertices.size());
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        if (!first) {
            out << ',';
        }
        first = false;
        write_preview_triangle_group(
            out,
            submesh_index,
            vertices,
            faces,
            normals,
            uvs,
            string_or(item.get("preview_triangle_output_path"), ""),
            source_vertices,
            source_faces
        );
    }
    out << "]}";
    return out.str();
}

std::string preview_vertex_update_groups_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_vertex_update_groups\",\"groups\":[";
    bool first = true;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("source_submesh_index"), int_or(item.get("index"), -1));
        if (submesh_index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        if (vertices.empty()) {
            continue;
        }
        const std::vector<int> source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());
        const bool changed_all_vertices = bool_or(item.get("changed_all_vertices"), false);
        const std::string preview_vertex_path = string_or(item.get("preview_vertex_output_path"), "");
        const int changed_vertex_start = int_or(item.get("changed_vertex_start"), -1);
        const int changed_vertex_count = int_or(item.get("changed_vertex_count"), 0);
        const bool changed_vertex_range = changed_vertex_start >= 0
            && changed_vertex_count > 0
            && changed_vertex_start <= static_cast<int>(vertices.size())
            && changed_vertex_count <= static_cast<int>(vertices.size()) - changed_vertex_start;
        if (changed_all_vertices && !preview_vertex_path.empty()) {
            if (!first) {
                out << ',';
            }
            first = false;
            write_full_preview_vertex_update_group(
                out,
                submesh_index,
                vertices,
                mesh_normals_from_item(item),
                mesh_uvs_from_item(item),
                preview_vertex_path,
                source_vertex_map
            );
            continue;
        }
        std::vector<int> changed_vertices;
        if (changed_all_vertices) {
            changed_vertices.reserve(vertices.size());
            for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
                changed_vertices.push_back(static_cast<int>(vertex_index));
            }
        } else if (changed_vertex_range) {
            changed_vertices.reserve(static_cast<std::size_t>(changed_vertex_count));
            for (int offset = 0; offset < changed_vertex_count; ++offset) {
                changed_vertices.push_back(changed_vertex_start + offset);
            }
        } else {
            changed_vertices = int_vector_from_binary_or_json(item, "changed_vertices_binary", "changed_vertices");
        }
        if (changed_vertices.empty()) {
            changed_vertices = int_vector_from_binary_or_json(
                item,
                "source_vertex_indices_binary",
                "source_vertex_indices",
                "source_vertex_start",
                "source_vertex_count"
            );
        }
        changed_vertices = valid_vertex_indices(changed_vertices, vertices.size());
        if (changed_vertices.empty()) {
            continue;
        }
        std::vector<Vec3> changed_positions;
        changed_positions.reserve(changed_vertices.size());
        for (const int vertex_index : changed_vertices) {
            changed_positions.push_back(vertices[static_cast<std::size_t>(vertex_index)]);
        }
        if (!preview_vertex_path.empty()) {
            write_vec3_binary_file(preview_vertex_path, changed_positions);
        }
        if (!first) {
            out << ',';
        }
        first = false;
        write_sparse_preview_vertex_update_group(
            out,
            submesh_index,
            changed_vertices,
            changed_positions,
            mesh_normals_from_item(item),
            mesh_uvs_from_item(item),
            preview_vertex_path,
            changed_all_vertices ? 0 : (changed_vertex_range ? changed_vertex_start : -1),
            source_vertex_map
        );
    }
    out << "]}";
    return out.str();
}

std::vector<SubmeshPreviewDecimateResult> run_preview_decimate(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }

    std::vector<SubmeshPreviewDecimateResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const int max_faces = int_or(item.get("max_faces"), 0);
        if (submesh_index < 0 || max_faces <= 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (vertices.empty() || faces.size() <= static_cast<std::size_t>(max_faces)) {
            continue;
        }

        SubmeshPreviewDecimateResult result;
        result.index = submesh_index;
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");

        const std::size_t step = std::max<std::size_t>(1, (faces.size() + static_cast<std::size_t>(max_faces) - 1u) / static_cast<std::size_t>(max_faces));
        std::map<int, int> source_to_preview;
        std::vector<int> source_remap;
        source_remap.reserve(static_cast<std::size_t>(max_faces) * 3u);
        result.faces.reserve(static_cast<std::size_t>(max_faces));
        result.vertices.reserve(static_cast<std::size_t>(max_faces) * 3u);

        for (std::size_t face_index = 0; face_index < faces.size() && result.faces.size() < static_cast<std::size_t>(max_faces); face_index += step) {
            std::array<int, 3> remapped_face{0, 0, 0};
            bool valid_face = true;
            for (std::size_t corner = 0; corner < 3; ++corner) {
                const int source_index = faces[face_index][corner];
                if (source_index < 0 || static_cast<std::size_t>(source_index) >= vertices.size()) {
                    valid_face = false;
                    break;
                }
                auto found = source_to_preview.find(source_index);
                if (found == source_to_preview.end()) {
                    const int preview_index = static_cast<int>(result.vertices.size());
                    source_to_preview[source_index] = preview_index;
                    source_remap.push_back(source_index);
                    result.vertices.push_back(vertices[static_cast<std::size_t>(source_index)]);
                    remapped_face[corner] = preview_index;
                } else {
                    remapped_face[corner] = found->second;
                }
            }
            if (valid_face) {
                result.faces.push_back(remapped_face);
            }
        }

        if (result.faces.empty()) {
            continue;
        }

        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (uvs.size() == vertices.size()) {
            result.uvs = copy_values_by_vertex_remap(uvs, source_remap);
        }
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        if (normals.size() == vertices.size()) {
            result.normals = copy_values_by_vertex_remap(normals, source_remap);
        }
        const BoneAssignments bones = mesh_bones_from_item(item);
        if (valid_bone_assignments(bones) && bones.indices.size() == vertices.size()) {
            result.bones = copy_bones_by_vertex_remap(bones, source_remap);
        }
        const std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
            item,
            "source_vertex_map_binary",
            "source_vertex_map",
            "source_vertex_map_start",
            "source_vertex_map_count"
        );
        if (source_vertex_map.size() == vertices.size()) {
            result.source_vertex_map = copy_values_by_vertex_remap(source_vertex_map, source_remap);
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::string preview_decimate_report_json(const JsonValue& root) {
    const std::vector<SubmeshPreviewDecimateResult> results = run_preview_decimate(root);
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_decimate\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        const SubmeshPreviewDecimateResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertices.size()
            << ",\"face_count\":" << result.faces.size();
        if (!result.vertices_path.empty()) {
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        }
        if (!result.faces_path.empty()) {
            std::vector<int> flat_faces;
            flat_faces.reserve(result.faces.size() * 3u);
            for (const std::array<int, 3>& face : result.faces) {
                flat_faces.push_back(face[0]);
                flat_faces.push_back(face[1]);
                flat_faces.push_back(face[2]);
            }
            write_int_binary_file(result.faces_path, flat_faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
        }
        if (!result.uvs_path.empty() && result.uvs.size() == result.vertices.size()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        }
        if (!result.normals_path.empty() && result.normals.size() == result.vertices.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (!result.bone_counts_path.empty()
            && !result.bone_indices_path.empty()
            && !result.bone_weights_path.empty()
            && valid_bone_assignments(result.bones)
            && result.bones.indices.size() == result.vertices.size()) {
            const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
            const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
            if (bone_counts.size() == result.vertices.size() && flat_bone_indices.size() == flat_bone_weights.size()) {
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
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string merge_submeshes_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }

    struct MergeInput {
        std::vector<Vec3> vertices;
        std::vector<std::array<int, 3>> faces;
        std::vector<Vec3> normals;
        std::vector<Vec2> uvs;
    };

    std::vector<MergeInput> inputs;
    inputs.reserve(submeshes->array_value.size());
    bool wants_normals = false;
    bool wants_uvs = false;
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        MergeInput input;
        input.vertices = mesh_vertices_from_item(item);
        input.faces = mesh_faces_from_item(item, input.vertices.size());
        input.normals = mesh_normals_from_item(item);
        input.uvs = mesh_uvs_from_item(item);
        if (input.normals.size() == input.vertices.size() && !input.vertices.empty()) {
            wants_normals = true;
        }
        if (input.uvs.size() == input.vertices.size() && !input.vertices.empty()) {
            wants_uvs = true;
        }
        vertex_count += input.vertices.size();
        face_count += input.faces.size();
        inputs.push_back(std::move(input));
    }

    std::vector<Vec3> merged_vertices;
    std::vector<std::array<int, 3>> merged_faces;
    std::vector<Vec3> merged_normals;
    std::vector<Vec2> merged_uvs;
    merged_vertices.reserve(vertex_count);
    merged_faces.reserve(face_count);
    if (wants_normals) {
        merged_normals.reserve(vertex_count);
    }
    if (wants_uvs) {
        merged_uvs.reserve(vertex_count);
    }

    int base = 0;
    for (const MergeInput& input : inputs) {
        merged_vertices.insert(merged_vertices.end(), input.vertices.begin(), input.vertices.end());
        if (wants_normals) {
            if (input.normals.size() == input.vertices.size()) {
                merged_normals.insert(merged_normals.end(), input.normals.begin(), input.normals.end());
            } else {
                merged_normals.insert(merged_normals.end(), input.vertices.size(), Vec3{0.0, 1.0, 0.0});
            }
        }
        if (wants_uvs) {
            if (input.uvs.size() == input.vertices.size()) {
                merged_uvs.insert(merged_uvs.end(), input.uvs.begin(), input.uvs.end());
            } else {
                merged_uvs.insert(merged_uvs.end(), input.vertices.size(), Vec2{0.0, 0.0});
            }
        }
        for (const std::array<int, 3>& face : input.faces) {
            merged_faces.push_back({face[0] + base, face[1] + base, face[2] + base});
        }
        base += static_cast<int>(input.vertices.size());
    }
    if (merged_normals.size() != merged_vertices.size()) {
        merged_normals = compute_smooth_normals(merged_vertices, merged_faces);
    }

    const std::string vertices_path = string_or(root.get("vertices_output_path"), "");
    const std::string faces_path = string_or(root.get("faces_output_path"), "");
    const std::string normals_path = string_or(root.get("normals_output_path"), "");
    const std::string uvs_path = string_or(root.get("uvs_output_path"), "");
    if (!vertices_path.empty()) {
        write_vec3_binary_file(vertices_path, merged_vertices);
    }
    if (!faces_path.empty()) {
        std::vector<int> merged_face_indices;
        merged_face_indices.reserve(merged_faces.size() * 3u);
        for (const std::array<int, 3>& face : merged_faces) {
            merged_face_indices.push_back(face[0]);
            merged_face_indices.push_back(face[1]);
            merged_face_indices.push_back(face[2]);
        }
        write_int_binary_file(faces_path, merged_face_indices);
    }
    if (!normals_path.empty()) {
        write_vec3_binary_file(normals_path, merged_normals);
    }
    if (!uvs_path.empty() && merged_uvs.size() == merged_vertices.size()) {
        write_vec2_binary_file(uvs_path, merged_uvs);
    }

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"merge_submeshes\""
        << ",\"vertex_count\":" << merged_vertices.size()
        << ",\"face_count\":" << merged_faces.size();
    if (!vertices_path.empty()) {
        out << ",\"vertices_binary\":";
        write_vec3_binary_descriptor(out, vertices_path, merged_vertices.size());
    }
    if (!faces_path.empty()) {
        out << ",\"faces_binary\":";
        write_int_binary_descriptor(out, faces_path, merged_faces.size(), 3);
    }
    if (!normals_path.empty()) {
        out << ",\"normals_binary\":";
        write_vec3_binary_descriptor(out, normals_path, merged_normals.size());
    }
    if (!uvs_path.empty() && merged_uvs.size() == merged_vertices.size()) {
        out << ",\"uvs_binary\":";
        write_vec2_binary_descriptor(out, uvs_path, merged_uvs.size());
    }
    out << '}';
    return out.str();
}

Vec3 bounds_center_for_vertices(const std::vector<Vec3>& vertices) {
    if (vertices.empty()) {
        return {0.0, 0.0, 0.0};
    }
    Vec3 minimum = vertices.front();
    Vec3 maximum = vertices.front();
    for (const Vec3& vertex : vertices) {
        for (int axis = 0; axis < 3; ++axis) {
            minimum[axis] = std::min(minimum[axis], vertex[axis]);
            maximum[axis] = std::max(maximum[axis], vertex[axis]);
        }
    }
    return {
        (minimum[0] + maximum[0]) * 0.5,
        (minimum[1] + maximum[1]) * 0.5,
        (minimum[2] + maximum[2]) * 0.5,
    };
}

Transform source_part_adjustment_transform(const JsonValue& adjustment, const std::vector<Vec3>& vertices) {
    Transform transform;
    transform.translate = vec3_or(adjustment.get("offset_xyz"), transform.translate);
    transform.scale = vec3_or(adjustment.get("scale_xyz"), transform.scale);
    const double uniform = number_or(adjustment.get("uniform_scale"), 1.0);
    transform.scale = {
        transform.scale[0] * uniform,
        transform.scale[1] * uniform,
        transform.scale[2] * uniform,
    };
    transform.rotate = vec3_or(adjustment.get("rotate_xyz_degrees"), transform.rotate);
    const std::vector<Vec3> pivot_vertices = vertices_from_binary_or_json(
        adjustment,
        "pivot_vertices_binary",
        "pivot_vertices"
    );
    const Vec3 default_pivot = pivot_vertices.empty()
        ? bounds_center_for_vertices(vertices)
        : bounds_center_for_vertices(pivot_vertices);
    transform.pivot = adjustment.get("pivot") != nullptr
        ? vec3_or(adjustment.get("pivot"), default_pivot)
        : default_pivot;
    return transform;
}
