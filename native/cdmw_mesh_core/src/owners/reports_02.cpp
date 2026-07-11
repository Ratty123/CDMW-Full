std::string affine_transform_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"affine_transform\",\"submeshes\":[";
    bool first = true;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        if (submesh_index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const JsonValue* source_part_adjustment = item.get("source_part_adjustment");
        const bool has_source_part_adjustment = source_part_adjustment != nullptr
            && source_part_adjustment->type == JsonValue::Type::Object;
        Transform source_part_transform;
        if (has_source_part_adjustment) {
            source_part_transform = source_part_adjustment_transform(*source_part_adjustment, vertices);
            for (Vec3& vertex : vertices) {
                vertex = transform_vertex(vertex, source_part_transform);
            }
        } else {
            std::vector<double> matrix = double_vector_from_json(item.get("position_matrix"));
            if (matrix.size() != 12) {
                throw std::runtime_error("position_matrix must contain 12 values");
            }
            for (const double value : matrix) {
                if (!std::isfinite(value)) {
                    throw std::runtime_error("non-finite position_matrix value");
                }
            }
            for (Vec3& vertex : vertices) {
                const double x = vertex[0];
                const double y = vertex[1];
                const double z = vertex[2];
                vertex = {
                    matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
                    matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
                    matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
                };
            }
        }

        std::vector<Vec3> normals = mesh_normals_from_item(item);
        std::vector<double> normal_matrix = double_vector_from_json(item.get("normal_matrix"));
        if (!normal_matrix.empty() && normal_matrix.size() != 9) {
            throw std::runtime_error("normal_matrix must contain 9 values");
        }
        if (normal_matrix.size() == 9 && normals.size() == vertices.size()) {
            for (Vec3& normal : normals) {
                const double x = normal[0];
                const double y = normal[1];
                const double z = normal[2];
                normal = normalized_vec3(
                    {
                        normal_matrix[0] * x + normal_matrix[1] * y + normal_matrix[2] * z,
                        normal_matrix[3] * x + normal_matrix[4] * y + normal_matrix[5] * z,
                        normal_matrix[6] * x + normal_matrix[7] * y + normal_matrix[8] * z,
                    },
                    {0.0, 1.0, 0.0}
                );
            }
        } else if (has_source_part_adjustment && normals.size() == vertices.size()) {
            Transform normal_transform;
            normal_transform.rotate = source_part_transform.rotate;
            for (Vec3& normal : normals) {
                normal = normalized_vec3(transform_vertex(normal, normal_transform), {0.0, 1.0, 0.0});
            }
        } else {
            normals.clear();
        }

        const bool mirror_x_around_bounds_center = bool_or(item.get("mirror_x_around_bounds_center"), false);
        if (mirror_x_around_bounds_center && !vertices.empty()) {
            const double plane_x = bounds_center_for_vertices(vertices)[0];
            for (Vec3& vertex : vertices) {
                vertex[0] = 2.0 * plane_x - vertex[0];
            }
            if (normals.size() == vertices.size()) {
                for (Vec3& normal : normals) {
                    normal[0] = -normal[0];
                    normal = normalized_vec3(normal, {0.0, 1.0, 0.0});
                }
            }
        }

        std::vector<std::array<int, 3>> faces;
        const bool reverse_face_winding = bool_or(item.get("reverse_face_winding"), false)
            || mirror_x_around_bounds_center;
        const std::string faces_path = string_or(item.get("faces_output_path"), "");
        if (reverse_face_winding || !faces_path.empty()) {
            faces = faces_from_binary_or_json(item, vertices.size());
            if (reverse_face_winding) {
                for (std::array<int, 3>& face : faces) {
                    std::swap(face[1], face[2]);
                }
            }
        }

        const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
        const std::string normals_path = string_or(item.get("normals_output_path"), "");
        if (!vertices_path.empty()) {
            write_vec3_binary_file(vertices_path, vertices);
        }
        if (!normals_path.empty() && normals.size() == vertices.size()) {
            write_vec3_binary_file(normals_path, normals);
        }
        if (!faces_path.empty()) {
            write_faces_binary_file(faces_path, faces);
        }
        if (!first) {
            out << ',';
        }
        first = false;
        out << "{\"index\":" << submesh_index
            << ",\"vertex_count\":" << vertices.size();
        if (!faces_path.empty()) {
            out << ",\"face_count\":" << faces.size();
        }
        if (!vertices_path.empty()) {
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, vertices_path, vertices.size());
        }
        if (!normals_path.empty() && normals.size() == vertices.size()) {
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, normals_path, normals.size());
        }
        if (!faces_path.empty()) {
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, faces_path, faces.size(), 3);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string string_from_ufbx(ufbx_string value) {
    if (value.data == nullptr || value.length == 0) {
        return std::string();
    }
    return std::string(value.data, value.length);
}

void write_string_array(std::ostream& out, const std::vector<std::string>& values) {
    out << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_escaped(out, values[i]);
    }
    out << ']';
}

std::string import_scene_report_json(const JsonValue& root) {
    const std::string source_path = string_or(root.get("source_path"));
    if (source_path.empty()) {
        throw std::runtime_error("source_path is required");
    }

    ufbx_load_opts opts = {};
    opts.generate_missing_normals = true;
    ufbx_error error = {};
    ufbx_scene* scene = ufbx_load_file_len(source_path.c_str(), source_path.size(), &opts, &error);
    if (scene == nullptr) {
        std::ostringstream out;
        out << "{\"status\":\"failed\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"import_scene\",\"import_backend\":\"ufbx\",\"source_path\":";
        write_escaped(out, source_path);
        out << ",\"error\":";
        write_escaped(out, string_from_ufbx(error.description));
        out << "}";
        return out.str();
    }

    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    std::size_t triangle_count = 0;
    std::size_t index_count = 0;
    bool has_uvs = false;
    bool has_normals = false;
    bool has_tangents = false;
    std::size_t max_weights_per_vertex = 0;
    for (std::size_t i = 0; i < scene->meshes.count; ++i) {
        const ufbx_mesh* mesh = scene->meshes.data[i];
        if (mesh == nullptr) {
            continue;
        }
        vertex_count += mesh->num_vertices;
        face_count += mesh->num_faces;
        triangle_count += mesh->num_triangles;
        index_count += mesh->num_indices;
        has_uvs = has_uvs || mesh->vertex_uv.exists;
        has_normals = has_normals || mesh->vertex_normal.exists;
        has_tangents = has_tangents || mesh->vertex_tangent.exists;
        for (std::size_t j = 0; j < mesh->skin_deformers.count; ++j) {
            const ufbx_skin_deformer* skin = mesh->skin_deformers.data[j];
            if (skin != nullptr && skin->max_weights_per_vertex > max_weights_per_vertex) {
                max_weights_per_vertex = skin->max_weights_per_vertex;
            }
        }
    }

    std::vector<std::string> material_names;
    for (std::size_t i = 0; i < scene->materials.count && material_names.size() < 64; ++i) {
        const ufbx_material* material = scene->materials.data[i];
        const std::string name = material != nullptr ? string_from_ufbx(material->name) : std::string();
        material_names.push_back(name.empty() ? std::string("material_") + std::to_string(i) : name);
    }

    std::vector<std::string> texture_files;
    for (std::size_t i = 0; i < scene->texture_files.count && texture_files.size() < 64; ++i) {
        const ufbx_texture_file& texture = scene->texture_files.data[i];
        std::string filename = string_from_ufbx(texture.filename);
        if (filename.empty()) {
            filename = string_from_ufbx(texture.relative_filename);
        }
        if (!filename.empty()) {
            texture_files.push_back(filename);
        }
    }

    std::vector<std::string> animation_names;
    for (std::size_t i = 0; i < scene->anim_stacks.count && animation_names.size() < 64; ++i) {
        const ufbx_anim_stack* stack = scene->anim_stacks.data[i];
        const std::string name = stack != nullptr ? string_from_ufbx(stack->name) : std::string();
        animation_names.push_back(name.empty() ? std::string("animation_") + std::to_string(i) : name);
    }

    std::vector<std::string> unsupported;
    if (scene->skin_deformers.count || scene->bones.count || scene->skin_clusters.count) {
        unsupported.push_back("fbx_rig_mapping_report_only");
    }
    if (scene->anim_stacks.count || scene->anim_layers.count || scene->anim_curves.count) {
        unsupported.push_back("fbx_animation_report_only");
    }
    if (scene->blend_deformers.count || scene->blend_shapes.count) {
        unsupported.push_back("fbx_blend_shapes_report_only");
    }
    if (scene->cache_deformers.count || scene->cache_files.count) {
        unsupported.push_back("fbx_geometry_cache_report_only");
    }

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"import_scene\",\"import_backend\":\"ufbx\",\"source_path\":";
    write_escaped(out, source_path);
    out << ",\"source_format\":\"fbx\",\"crimson_compatibility\":\"unmapped\",\"mesh\":{"
        << "\"part_count\":" << scene->meshes.count
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"triangle_count\":" << triangle_count
        << ",\"index_count\":" << index_count
        << ",\"has_uvs\":" << (has_uvs ? "true" : "false")
        << ",\"has_normals\":" << (has_normals ? "true" : "false")
        << ",\"has_tangents\":" << (has_tangents ? "true" : "false")
        << "},\"materials\":{\"count\":" << scene->materials.count << ",\"names\":";
    write_string_array(out, material_names);
    out << "},\"texture_hints\":{\"count\":" << scene->texture_files.count << ",\"files\":";
    write_string_array(out, texture_files);
    out << "},\"skeleton_hints\":{"
        << "\"has_skinning\":" << (scene->skin_deformers.count ? "true" : "false")
        << ",\"bone_count\":" << scene->bones.count
        << ",\"skin_deformer_count\":" << scene->skin_deformers.count
        << ",\"skin_cluster_count\":" << scene->skin_clusters.count
        << ",\"max_weights_per_vertex\":" << max_weights_per_vertex
        << ",\"rig_status\":";
    write_escaped(out, (scene->skin_deformers.count || scene->bones.count) ? "reported_unsupported_until_crimson_mapping" : "none");
    out << ",\"animation_status\":";
    write_escaped(out, scene->anim_stacks.count ? "reported_unsupported_until_crimson_mapping" : "none");
    out << "},\"animations\":{\"count\":" << scene->anim_stacks.count << ",\"names\":";
    write_string_array(out, animation_names);
    out << "},\"unsupported\":";
    write_string_array(out, unsupported);
    out << ",\"diagnostics\":[";
    write_escaped(out, "FBX parsed with ufbx; Crimson compatibility remains unmapped until assigned to a target asset.");
    if (!unsupported.empty()) {
        out << ',';
        write_escaped(out, "Rig, animation, blend shape, or cache data is reported only and not imported into game-ready output.");
    }
    out << "]}";
    ufbx_free_scene(scene);
    return out.str();
}

std::string tangent_backend_summary(const std::vector<SubmeshTangentsResult>& results) {
    if (results.empty()) {
        return "none";
    }
    std::string backend = results.front().tangent_backend;
    for (const SubmeshTangentsResult& result : results) {
        if (result.tangent_backend != backend) {
            return "mixed";
        }
    }
    return backend;
}

void write_command_metrics(std::ostream& out, double cpp_ms) {
    out << "\"metrics\":{\"cpp_ms\":" << cpp_ms
        << ",\"io_serialization_ms\":0,\"python_apply_ms\":0,\"d3d11_update_ms\":0}";
}

std::string selection_report_json(const std::vector<SubmeshSelectionResult>& results, double cpp_ms = 0.0) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshSelectionResult& result = results[i];
        out << "{\"index\":" << result.index;
        int selected_vertex_start = -1;
        if (contiguous_int_range(result.selected_vertices, selected_vertex_start)) {
            out << ",\"selected_vertex_start\":" << selected_vertex_start
                << ",\"selected_vertex_count\":" << result.selected_vertices.size();
        } else if (!result.selected_vertices_path.empty()) {
            write_int_binary_file(result.selected_vertices_path, result.selected_vertices);
            out << ",\"selected_vertices_binary\":";
            write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1);
        } else {
            out << ",\"selected_vertices\":[";
            for (std::size_t j = 0; j < result.selected_vertices.size(); ++j) {
                if (j) {
                    out << ',';
                }
                out << result.selected_vertices[j];
            }
            out << ']';
        }
        out << "}";
    }
    out << "],";
    write_command_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string uv_selection_report_json(const std::vector<SubmeshUvSelectionResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"uv_selection\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshUvSelectionResult& result = results[i];
        out << "{\"index\":" << result.index;
        int selected_vertex_start = -1;
        if (contiguous_int_range(result.selected_vertices, selected_vertex_start)) {
            out << ",\"selected_vertex_start\":" << selected_vertex_start
                << ",\"selected_vertex_count\":" << result.selected_vertices.size();
        } else if (!result.selected_vertices_path.empty()) {
            write_int_binary_file(result.selected_vertices_path, result.selected_vertices);
            out << ",\"selected_vertices_binary\":";
            write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1);
        } else {
            out << ",\"selected_vertices\":";
            write_int_vector(out, result.selected_vertices);
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string uv_summary_report_json(const std::vector<UvIslandSummaryResult>& islands) {
    std::ostringstream out;
    int selected_count = 0;
    for (const UvIslandSummaryResult& island : islands) {
        if (island.selected) {
            ++selected_count;
        }
    }
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"uv_summary\""
        << ",\"island_count\":" << islands.size()
        << ",\"selected_island_count\":" << selected_count
        << ",\"islands\":[";
    for (std::size_t i = 0; i < islands.size(); ++i) {
        if (i) {
            out << ',';
        }
        const UvIslandSummaryResult& island = islands[i];
        out << "{\"index\":" << island.index
            << ",\"submesh_index\":" << island.submesh_index
            << ",\"part_name\":";
        write_escaped(out, island.part_name);
        out << ",\"material\":";
        write_escaped(out, island.material);
        out << ",\"texture\":";
        write_escaped(out, island.texture);
        out << ",\"vertex_count\":" << island.vertex_count
            << ",\"face_count\":" << island.face_count
            << ",\"uv_min\":[" << island.uv_min[0] << ',' << island.uv_min[1] << ']'
            << ",\"uv_max\":[" << island.uv_max[0] << ',' << island.uv_max[1] << ']'
            << ",\"selected\":" << (island.selected ? "true" : "false")
            << ",\"selected_vertex_count\":" << island.selected_vertex_count
            << ",\"selected_face_count\":" << island.selected_face_count
            << '}';
    }
    out << "]}";
    return out.str();
}

std::string mesh_metadata_report_json(const std::vector<SubmeshMetadataResult>& results) {
    std::size_t total_vertices = 0;
    std::size_t total_faces = 0;
    bool has_uvs = false;
    bool has_bounds = false;
    Vec3 bbox_min{0.0, 0.0, 0.0};
    Vec3 bbox_max{0.0, 0.0, 0.0};
    for (const SubmeshMetadataResult& result : results) {
        total_vertices += result.vertex_count;
        total_faces += result.face_count;
        has_uvs = has_uvs || result.has_uvs;
        if (!result.has_bounds) {
            continue;
        }
        if (!has_bounds) {
            bbox_min = result.bbox_min;
            bbox_max = result.bbox_max;
            has_bounds = true;
        } else {
            bbox_min[0] = std::min(bbox_min[0], result.bbox_min[0]);
            bbox_min[1] = std::min(bbox_min[1], result.bbox_min[1]);
            bbox_min[2] = std::min(bbox_min[2], result.bbox_min[2]);
            bbox_max[0] = std::max(bbox_max[0], result.bbox_max[0]);
            bbox_max[1] = std::max(bbox_max[1], result.bbox_max[1]);
            bbox_max[2] = std::max(bbox_max[2], result.bbox_max[2]);
        }
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"mesh_metadata\""
        << ",\"submesh_count\":" << results.size()
        << ",\"total_vertices\":" << total_vertices
        << ",\"total_faces\":" << total_faces
        << ",\"has_uvs\":" << (has_uvs ? "true" : "false")
        << ",\"has_bounds\":" << (has_bounds ? "true" : "false")
        << ",\"bbox_min\":";
    write_vec3(out, has_bounds ? bbox_min : Vec3{0.0, 0.0, 0.0});
    out << ",\"bbox_max\":";
    write_vec3(out, has_bounds ? bbox_max : Vec3{0.0, 0.0, 0.0});
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMetadataResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"face_count\":" << result.face_count
            << ",\"has_uvs\":" << (result.has_uvs ? "true" : "false")
            << ",\"has_bounds\":" << (result.has_bounds ? "true" : "false")
            << ",\"bbox_min\":";
        write_vec3(out, result.has_bounds ? result.bbox_min : Vec3{0.0, 0.0, 0.0});
        out << ",\"bbox_max\":";
        write_vec3(out, result.has_bounds ? result.bbox_max : Vec3{0.0, 0.0, 0.0});
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string selection_bounds_report_json(const std::vector<SubmeshSelectionBoundsResult>& results) {
    std::size_t selected_vertex_count = 0;
    bool has_bounds = false;
    Vec3 bbox_min{0.0, 0.0, 0.0};
    Vec3 bbox_max{0.0, 0.0, 0.0};
    for (const SubmeshSelectionBoundsResult& result : results) {
        selected_vertex_count += result.selected_vertex_count;
        if (!result.has_bounds) {
            continue;
        }
        if (!has_bounds) {
            bbox_min = result.bbox_min;
            bbox_max = result.bbox_max;
            has_bounds = true;
        } else {
            bbox_min[0] = std::min(bbox_min[0], result.bbox_min[0]);
            bbox_min[1] = std::min(bbox_min[1], result.bbox_min[1]);
            bbox_min[2] = std::min(bbox_min[2], result.bbox_min[2]);
            bbox_max[0] = std::max(bbox_max[0], result.bbox_max[0]);
            bbox_max[1] = std::max(bbox_max[1], result.bbox_max[1]);
            bbox_max[2] = std::max(bbox_max[2], result.bbox_max[2]);
        }
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection_bounds\""
        << ",\"submesh_count\":" << results.size()
        << ",\"selected_vertex_count\":" << selected_vertex_count
        << ",\"has_bounds\":" << (has_bounds ? "true" : "false")
        << ",\"bbox_min\":";
    write_vec3(out, has_bounds ? bbox_min : Vec3{0.0, 0.0, 0.0});
    out << ",\"bbox_max\":";
    write_vec3(out, has_bounds ? bbox_max : Vec3{0.0, 0.0, 0.0});
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshSelectionBoundsResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"selected_vertex_count\":" << result.selected_vertex_count
            << ",\"has_bounds\":" << (result.has_bounds ? "true" : "false")
            << ",\"bbox_min\":";
        write_vec3(out, result.has_bounds ? result.bbox_min : Vec3{0.0, 0.0, 0.0});
        out << ",\"bbox_max\":";
        write_vec3(out, result.has_bounds ? result.bbox_max : Vec3{0.0, 0.0, 0.0});
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::vector<int> flatten_selection_edges(const std::vector<std::array<int, 2>>& edges) {
    std::vector<int> values;
    values.reserve(edges.size() * 2u);
    for (const auto& edge : edges) {
        values.push_back(edge[0]);
        values.push_back(edge[1]);
    }
    return values;
}

std::vector<int> flatten_vertex_blend_indices(const std::vector<VertexBlend>& blends) {
    std::vector<int> values;
    values.reserve(blends.size() * 3u);
    for (const VertexBlend& blend : blends) {
        values.push_back(blend.index);
        values.push_back(blend.left);
        values.push_back(blend.right);
    }
    return values;
}

std::vector<double> flatten_vertex_blend_factors(const std::vector<VertexBlend>& blends) {
    std::vector<double> values;
    values.reserve(blends.size());
    for (const VertexBlend& blend : blends) {
        values.push_back(blend.factor);
    }
    return values;
}

void write_selection_preview_group(std::ostream& out, const SubmeshSelectionPreviewResult& result) {
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << result.index;
    if (!result.selection_preview_path.empty()) {
        const std::string source_edges_path = sibling_binary_path(result.selection_preview_path, ".source_edges.bin");
        const std::string source_faces_path = sibling_binary_path(result.selection_preview_path, ".source_faces.bin");
        int source_vertex_start = -1;
        if (contiguous_int_range(result.source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << result.source_vertex_indices.size();
        } else {
            write_int_binary_file(result.selection_preview_path, result.source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_preview_binary_descriptor(out, result.selection_preview_path, result.source_vertex_indices.size(), 1, "i32");
        }
        if (!result.source_edges.empty()) {
            write_int_binary_file(source_edges_path, flatten_selection_edges(result.source_edges));
            out << ",\"source_edges_binary\":";
            write_preview_binary_descriptor(out, source_edges_path, result.source_edges.size(), 2, "i32");
        }
        if (!result.source_face_indices.empty()) {
            int source_face_start = -1;
            if (contiguous_int_range(result.source_face_indices, source_face_start)) {
                out << ",\"source_face_start\":" << source_face_start
                    << ",\"source_face_count\":" << result.source_face_indices.size();
            } else {
                write_int_binary_file(source_faces_path, result.source_face_indices);
                out << ",\"source_face_indices_binary\":";
                write_preview_binary_descriptor(out, source_faces_path, result.source_face_indices.size(), 1, "i32");
            }
        }
        out << '}';
        return;
    }
    int source_vertex_start = -1;
    if (contiguous_int_range(result.source_vertex_indices, source_vertex_start)) {
        out << ",\"source_vertex_start\":" << source_vertex_start
            << ",\"source_vertex_count\":" << result.source_vertex_indices.size();
    } else {
        out << ",\"source_vertex_indices\":";
        write_int_vector(out, result.source_vertex_indices);
    }
    if (!result.source_edges.empty()) {
        out << ",\"source_edges\":[";
        for (std::size_t edge_index = 0; edge_index < result.source_edges.size(); ++edge_index) {
            if (edge_index) {
                out << ',';
            }
            out << '[' << result.source_edges[edge_index][0] << ',' << result.source_edges[edge_index][1] << ']';
        }
        out << ']';
    }
    if (!result.source_face_indices.empty()) {
        int source_face_start = -1;
        if (contiguous_int_range(result.source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << result.source_face_indices.size();
        } else {
            out << ",\"source_face_indices\":";
            write_int_vector(out, result.source_face_indices);
        }
    }
    out << '}';
}

std::string selection_preview_report_json(const std::vector<SubmeshSelectionPreviewResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection_preview\",\"groups\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshSelectionPreviewResult& result = results[i];
        write_selection_preview_group(out, result);
    }
    out << "]}";
    return out.str();
}

void write_selection_prune_item(std::ostream& out, const SubmeshSelectionPruneResult& result) {
    out << "{\"index\":" << result.index;
    if (!result.selected_vertices.empty()) {
        int selected_vertex_start = -1;
        if (contiguous_int_range(result.selected_vertices, selected_vertex_start)) {
            out << ",\"selected_vertex_start\":" << selected_vertex_start
                << ",\"selected_vertex_count\":" << result.selected_vertices.size();
        } else if (!result.selected_vertices_path.empty()) {
            write_int_binary_file(result.selected_vertices_path, result.selected_vertices);
            out << ",\"selected_vertices_binary\":";
            write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1);
        } else {
            out << ",\"selected_vertices\":";
            write_int_vector(out, result.selected_vertices);
        }
    }
    if (!result.selected_edges.empty()) {
        if (!result.selected_edges_path.empty()) {
            write_int_binary_file(result.selected_edges_path, flatten_selection_edges(result.selected_edges));
            out << ",\"selected_edges_binary\":";
            write_int_binary_descriptor(out, result.selected_edges_path, result.selected_edges.size(), 2);
        } else {
            out << ",\"selected_edges\":[";
            for (std::size_t edge_index = 0; edge_index < result.selected_edges.size(); ++edge_index) {
                if (edge_index) {
                    out << ',';
                }
                out << '[' << result.selected_edges[edge_index][0] << ',' << result.selected_edges[edge_index][1] << ']';
            }
            out << ']';
        }
    }
    if (!result.selected_faces.empty()) {
        int selected_face_start = -1;
        if (contiguous_int_range(result.selected_faces, selected_face_start)) {
            out << ",\"selected_face_start\":" << selected_face_start
                << ",\"selected_face_count\":" << result.selected_faces.size();
        } else if (!result.selected_faces_path.empty()) {
            write_int_binary_file(result.selected_faces_path, result.selected_faces);
            out << ",\"selected_faces_binary\":";
            write_int_binary_descriptor(out, result.selected_faces_path, result.selected_faces.size(), 1);
        } else {
            out << ",\"selected_faces\":";
            write_int_vector(out, result.selected_faces);
        }
    }
    out << '}';
}

std::string selection_prune_report_json(const std::vector<SubmeshSelectionPruneResult>& results, double cpp_ms = 0.0) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection_prune\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_selection_prune_item(out, results[i]);
    }
    out << "],";
    write_command_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string mesh_editor_delta_path(
    const std::string& directory,
    const std::string& session_id,
    int submesh_index,
    const std::string& role,
    const std::string& suffix
);

std::vector<SubmeshSelectionPruneResult> mesh_editor_selection_report_items(
    const MeshEditorSelection& selection,
    const std::string& output_dir,
    const std::string& session_id
) {
    std::set<int> targets;
    for (const auto& mapping : {selection.vertices, selection.faces}) {
        for (const auto& entry : mapping) {
            targets.insert(entry.first);
        }
    }
    for (const auto& entry : selection.edges) {
        targets.insert(entry.first);
    }
    std::vector<SubmeshSelectionPruneResult> results;
    for (const int submesh_index : targets) {
        SubmeshSelectionPruneResult result;
        result.index = submesh_index;
        const auto vertices = selection.vertices.find(submesh_index);
        if (vertices != selection.vertices.end()) {
            result.selected_vertices.assign(vertices->second.begin(), vertices->second.end());
        }
        const auto edges = selection.edges.find(submesh_index);
        if (edges != selection.edges.end()) {
            result.selected_edges.assign(edges->second.begin(), edges->second.end());
        }
        const auto faces = selection.faces.find(submesh_index);
        if (faces != selection.faces.end()) {
            result.selected_faces.assign(faces->second.begin(), faces->second.end());
        }
        if (!output_dir.empty()) {
            result.selected_vertices_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_vertices", ".bin");
            result.selected_edges_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_edges", ".bin");
            result.selected_faces_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_faces", ".bin");
        }
        results.push_back(std::move(result));
    }
    return results;
}
