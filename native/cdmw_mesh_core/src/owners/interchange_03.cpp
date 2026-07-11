void write_f64_binary_descriptor(std::ostream& out, const std::string& path, std::size_t count) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count << ",\"components\":1,\"type\":\"f64\"}";
}

void write_int_binary_descriptor(std::ostream& out, const std::string& path, std::size_t count, int components) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count << ",\"components\":" << components << ",\"type\":\"i32\"}";
}

std::string static_donor_indices_report_json(const std::vector<SubmeshStaticDonorIndicesResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"static_donor_indices\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const SubmeshStaticDonorIndicesResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"original_vertex_count\":" << result.original_vertex_count
            << ",\"new_vertex_count\":" << result.new_vertex_count
            << ",\"sequence_alignment_used\":" << (result.sequence_alignment_used ? "true" : "false")
            << ",\"sequence_alignment_fallback\":" << (result.sequence_alignment_fallback ? "true" : "false")
            << ",\"donor_indices_binary\":";
        write_int_binary_descriptor(out, result.donor_indices_path, result.donor_indices.size(), 1);
        out << '}';
    }
    out << "]}";
    return out.str();
}

void write_changed_vertices_report(
    std::ostream& out,
    const std::vector<int>& changed_vertices,
    const std::string& changed_vertices_path,
    int& changed_vertex_start
);

std::string pose_preview_report_json(const std::vector<SubmeshPosePreviewResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"pose_preview\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const SubmeshPosePreviewResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"changed_count\":" << result.changed_vertices.size();
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        out << ",\"vertices_binary\":";
        write_vec3_binary_file(result.vertices_path, result.vertices);
        write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string skin_weights_report_json(const std::vector<SubmeshSkinWeightsResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"skin_weights\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const SubmeshSkinWeightsResult& result = results[index];
        const std::vector<int> counts = bone_assignment_counts(result.bones);
        const std::vector<int> flat_indices = flatten_bone_indices(result.bones);
        const std::vector<double> flat_weights = flatten_bone_weights(result.bones);
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"changed_count\":" << result.changed_vertices.size()
            << ",\"transfer_distance_p95\":" << result.transfer_distance_p95
            << ",\"transfer_distance_limit\":" << result.transfer_distance_limit
            << ",\"transfer_distance_warning\":" << (result.transfer_distance_warning ? "true" : "false");
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        out << ",\"bone_counts_binary\":";
        write_int_binary_descriptor(out, result.bone_counts_path, counts.size(), 1);
        out << ",\"bone_indices_binary\":";
        write_int_binary_descriptor(out, result.bone_indices_path, flat_indices.size(), 1);
        out << ",\"bone_weights_binary\":";
        write_f64_binary_descriptor(out, result.bone_weights_path, flat_weights.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string obj_export_report_json(const ObjExportResult& result) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"obj_export\",\"output_path\":";
    write_escaped(out, result.output_path);
    out << ",\"submesh_count\":" << result.submesh_count
        << ",\"vertex_count\":" << result.vertex_count
        << ",\"face_count\":" << result.face_count;
    if (!result.manifest_path.empty()) {
        out << ",\"manifest_path\":";
        write_escaped(out, result.manifest_path);
    }
    out << "}";
    return out.str();
}

std::string obj_manifest_report_json(const ObjManifestResult& result) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"obj_manifest\",\"manifest_path\":";
    write_escaped(out, result.manifest_path);
    out << ",\"submesh_count\":" << result.submesh_count
        << ",\"vertex_count\":" << result.vertex_count
        << ",\"face_count\":" << result.face_count
        << "}";
    return out.str();
}

std::string fbx_geometry_report_json(const std::vector<FbxGeometrySubmeshResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"fbx_geometry\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const FbxGeometrySubmeshResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"face_count\":" << result.face_count
            << ",\"normal_count\":" << result.normal_count
            << ",\"uv_count\":" << result.uv_count
            << ",\"vertices_binary\":";
        write_f64_binary_descriptor(out, result.vertices_path, result.vertex_value_count);
        out << ",\"indices_binary\":";
        write_int_binary_descriptor(out, result.indices_path, result.index_value_count, 1);
        out << ",\"normals_binary\":";
        write_f64_binary_descriptor(out, result.normals_path, result.normal_value_count);
        out << ",\"uvs_binary\":";
        write_f64_binary_descriptor(out, result.uvs_path, result.uv_value_count);
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string fbx_export_report_json(const FbxExportResult& result) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"fbx_export\",\"output_path\":";
    write_escaped(out, result.output_path);
    out << ",\"submesh_count\":" << result.submesh_count
        << ",\"vertex_count\":" << result.vertex_count
        << ",\"face_count\":" << result.face_count
        << "}";
    return out.str();
}

void write_preview_binary_descriptor(
    std::ostream& out,
    const std::string& path,
    std::size_t count,
    int components,
    const std::string& type
) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count
        << ",\"components\":" << components
        << ",\"type\":";
    write_escaped(out, type);
    out << ",\"delete_after\":true}";
}

std::string sibling_binary_path(const std::string& path, const std::string& suffix) {
    return path.empty() ? std::string() : path + suffix;
}

std::string morph_apply_report_json(const std::vector<SubmeshMorphApplyResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"morph_apply\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMorphApplyResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"normal_count\":" << result.normal_count
            << ",\"vertices_binary\":";
        write_escaped(out, result.vertices_path);
        out << ",\"normals_binary\":";
        write_escaped(out, result.normals_path);
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string morph_post_edit_delta_report_json(const std::vector<SubmeshMorphPostEditDeltaResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"morph_post_edit_delta\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMorphPostEditDeltaResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"zero_delta\":" << (result.zero_delta ? "true" : "false")
            << ",\"deltas_binary\":";
        if (result.zero_delta) {
            out << "null";
        } else {
            write_vec3_binary_descriptor(out, result.deltas_path, result.deltas.size());
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string morph_target_delta_report_json(const std::vector<SubmeshMorphPostEditDeltaResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"morph_target_delta\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMorphPostEditDeltaResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"deltas_binary\":";
        write_vec3_binary_descriptor(out, result.deltas_path, result.deltas.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string region_volume_delta_report_json(const std::vector<SubmeshRegionVolumeDeltaResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"region_volume_delta\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshRegionVolumeDeltaResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"selected_vertex_count\":" << result.selected_vertex_count
            << ",\"weighted_vertex_count\":" << result.weighted_vertex_count
            << ",\"deltas_binary\":";
        write_vec3_binary_descriptor(out, result.deltas_path, result.deltas.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::vector<int> valid_vertex_indices(const std::vector<int>& indices, std::size_t vertex_count) {
    std::vector<int> result;
    result.reserve(indices.size());
    for (const int index : indices) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.push_back(index);
        }
    }
    return result;
}

void write_flat_vec3_for_indices(std::ostream& out, const std::vector<Vec3>& values, const std::vector<int>& indices) {
    bool first = true;
    for (const int index : indices) {
        if (index < 0 || static_cast<std::size_t>(index) >= values.size()) {
            continue;
        }
        if (!first) {
            out << ',';
        }
        const Vec3& value = values[static_cast<std::size_t>(index)];
        out << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2];
        first = false;
    }
}

void write_flat_vec2_for_indices(std::ostream& out, const std::vector<Vec2>& values, const std::vector<int>& indices) {
    bool first = true;
    for (const int index : indices) {
        if (index < 0 || static_cast<std::size_t>(index) >= values.size()) {
            continue;
        }
        if (!first) {
            out << ',';
        }
        const Vec2& value = values[static_cast<std::size_t>(index)];
        out << std::setprecision(17) << value[0] << ',' << value[1];
        first = false;
    }
}

std::vector<int> source_vertex_ids_for_indices(
    const std::vector<int>& indices,
    const std::vector<int>& source_vertex_map,
    std::size_t count
) {
    const std::size_t limit = std::min(count, indices.size());
    std::vector<int> result;
    result.reserve(limit);
    const bool has_source_map = !source_vertex_map.empty();
    for (std::size_t index = 0; index < limit; ++index) {
        const int vertex_index = indices[index];
        if (has_source_map
            && vertex_index >= 0
            && static_cast<std::size_t>(vertex_index) < source_vertex_map.size()) {
            result.push_back(source_vertex_map[static_cast<std::size_t>(vertex_index)]);
        } else {
            result.push_back(vertex_index);
        }
    }
    return result;
}

bool preview_source_vertex_range_for_indices(
    const std::vector<int>& indices,
    const std::vector<int>& source_vertex_map,
    std::size_t count,
    int source_vertex_start_hint,
    int& source_vertex_start
) {
    source_vertex_start = -1;
    if (count == 0) {
        return false;
    }
    if (source_vertex_map.empty() && source_vertex_start_hint >= 0) {
        source_vertex_start = source_vertex_start_hint;
        return true;
    }
    if (indices.size() < count) {
        return false;
    }
    int previous = -1;
    for (std::size_t index = 0; index < count; ++index) {
        const int vertex_index = indices[index];
        if (vertex_index < 0) {
            return false;
        }
        int source_vertex = vertex_index;
        if (!source_vertex_map.empty()) {
            if (static_cast<std::size_t>(vertex_index) >= source_vertex_map.size()) {
                return false;
            }
            source_vertex = source_vertex_map[static_cast<std::size_t>(vertex_index)];
        }
        if (source_vertex < 0) {
            return false;
        }
        if (index == 0) {
            source_vertex_start = source_vertex;
        } else if (source_vertex != previous + 1) {
            source_vertex_start = -1;
            return false;
        }
        previous = source_vertex;
    }
    return source_vertex_start >= 0;
}

void write_preview_source_vertex_ids(
    std::ostream& out,
    const std::vector<int>& source_indices,
    const std::string& source_indices_path = std::string()
) {
    int source_vertex_start = -1;
    if (contiguous_int_range(source_indices, source_vertex_start)) {
        out << ",\"source_vertex_start\":" << source_vertex_start
            << ",\"source_vertex_count\":" << source_indices.size();
    } else if (!source_indices_path.empty()) {
        write_int_binary_file(source_indices_path, source_indices);
        out << ",\"source_vertex_indices_binary\":";
        write_preview_binary_descriptor(out, source_indices_path, source_indices.size(), 1, "i32");
    } else {
        out << ",\"source_vertex_indices\":[";
        for (std::size_t j = 0; j < source_indices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << source_indices[j];
        }
        out << ']';
    }
}

void write_preview_source_vertex_range(std::ostream& out, int source_vertex_start, std::size_t count) {
    out << ",\"source_vertex_start\":" << source_vertex_start
        << ",\"source_vertex_count\":" << count;
}

void write_preview_vertex_update_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<int>& changed_vertices,
    const std::vector<Vec3>& vertices,
    const std::vector<Vec3>& normals,
    const std::vector<Vec2>& uvs,
    const std::string& source_indices_path = std::string(),
    const std::vector<int>& source_vertex_map = std::vector<int>()
) {
    const std::vector<int> indices = valid_vertex_indices(changed_vertices, vertices.size());
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << submesh_index;
    write_preview_source_vertex_ids(out, source_vertex_ids_for_indices(indices, source_vertex_map, indices.size()), source_indices_path);
    out << ",\"positions\":[";
    write_flat_vec3_for_indices(out, vertices, indices);
    out << "],\"normals\":[";
    if (normals.size() == vertices.size()) {
        write_flat_vec3_for_indices(out, normals, indices);
    }
    out << "],\"uvs\":[";
    if (uvs.size() == vertices.size()) {
        write_flat_vec2_for_indices(out, uvs, indices);
    }
    out << "]}";
}

void write_sparse_preview_vertex_update_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<int>& changed_vertices,
    const std::vector<Vec3>& changed_positions,
    const std::vector<Vec3>& normals = {},
    const std::vector<Vec2>& uvs = {},
    const std::string& changed_positions_path = std::string(),
    int source_vertex_start = -1,
    const std::vector<int>& source_vertex_map = std::vector<int>(),
    const std::vector<int>& changed_source_vertex_ids = std::vector<int>()
) {
    const std::size_t count = std::min(changed_vertices.size(), changed_positions.size());
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << submesh_index;
    std::vector<int> source_indices;
    int direct_source_start = -1;
    const bool has_changed_source_ids = changed_source_vertex_ids.size() == count;
    if (has_changed_source_ids) {
        source_indices = changed_source_vertex_ids;
    }
    const bool direct_source_range = has_changed_source_ids
        ? contiguous_int_range(source_indices, direct_source_start)
        : preview_source_vertex_range_for_indices(
            changed_vertices,
            source_vertex_map,
            count,
            source_vertex_start,
            direct_source_start
        );
    if (direct_source_range) {
        write_preview_source_vertex_range(out, direct_source_start, count);
    } else if (!has_changed_source_ids) {
        source_indices = source_vertex_ids_for_indices(changed_vertices, source_vertex_map, count);
    }
    if (!changed_positions_path.empty()) {
        if (!direct_source_range) {
            write_preview_source_vertex_ids(
                out,
                source_indices,
                sibling_binary_path(changed_positions_path, ".source_indices.bin")
            );
        }
        out << ",\"positions_binary\":";
        write_preview_binary_descriptor(out, changed_positions_path, count, 3, "f64");
        if (!normals.empty()) {
            std::vector<Vec3> changed_normals;
            changed_normals.reserve(count);
            for (std::size_t index = 0; index < count; ++index) {
                const int vertex_index = changed_vertices[index];
                if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= normals.size()) {
                    changed_normals.clear();
                    break;
                }
                changed_normals.push_back(normals[static_cast<std::size_t>(vertex_index)]);
            }
            if (changed_normals.size() == count) {
                const std::string normals_path = sibling_binary_path(changed_positions_path, ".normals.bin");
                write_vec3_binary_file(normals_path, changed_normals);
                out << ",\"normals_binary\":";
                write_preview_binary_descriptor(out, normals_path, changed_normals.size(), 3, "f64");
            }
        }
        if (!uvs.empty()) {
            std::vector<Vec2> changed_uvs;
            changed_uvs.reserve(count);
            for (std::size_t index = 0; index < count; ++index) {
                const int vertex_index = changed_vertices[index];
                if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= uvs.size()) {
                    changed_uvs.clear();
                    break;
                }
                changed_uvs.push_back(uvs[static_cast<std::size_t>(vertex_index)]);
            }
            if (changed_uvs.size() == count) {
                const std::string uvs_path = sibling_binary_path(changed_positions_path, ".uvs.bin");
                write_vec2_binary_file(uvs_path, changed_uvs);
                out << ",\"uvs_binary\":";
                write_preview_binary_descriptor(out, uvs_path, changed_uvs.size(), 2, "f64");
            }
        }
        out << "}";
        return;
    }
    if (!direct_source_range) {
        write_preview_source_vertex_ids(out, source_indices);
    }
    out << ",\"positions\":[";
    for (std::size_t index = 0; index < count; ++index) {
        if (index > 0) {
            out << ',';
        }
        const Vec3& value = changed_positions[index];
        out << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2];
    }
    out << "],\"normals\":[";
    if (!normals.empty()) {
        bool first = true;
        for (std::size_t index = 0; index < count; ++index) {
            const int vertex_index = changed_vertices[index];
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= normals.size()) {
                continue;
            }
            if (!first) {
                out << ',';
            }
            const Vec3& value = normals[static_cast<std::size_t>(vertex_index)];
            out << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2];
            first = false;
        }
    }
    out << "],\"uvs\":[";
    if (!uvs.empty()) {
        bool first = true;
        for (std::size_t index = 0; index < count; ++index) {
            const int vertex_index = changed_vertices[index];
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= uvs.size()) {
                continue;
            }
            if (!first) {
                out << ',';
            }
            const Vec2& value = uvs[static_cast<std::size_t>(vertex_index)];
            out << std::setprecision(17) << value[0] << ',' << value[1];
            first = false;
        }
    }
    out << "]}";
}
