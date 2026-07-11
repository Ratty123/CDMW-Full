std::string cleanup_report_json(const std::vector<SubmeshCleanupResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const SubmeshCleanupResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"removed_vertices\":" << result.removed_vertices
            << ",\"removed_faces\":" << result.removed_faces
            << ",\"merged_vertices\":" << result.merged_vertices
            << ",\"degenerate_faces\":" << result.degenerate_faces
            << ",\"duplicate_faces\":" << result.duplicate_faces;
        if (result.suppress_index_map_report) {
            out << ",\"index_map_report_suppressed\":true";
        } else if (!result.index_map_path.empty()) {
            write_int_binary_file(result.index_map_path, result.index_map);
            out << ",\"index_map_binary\":";
            write_int_binary_descriptor(out, result.index_map_path, result.index_map.size(), 1);
        } else {
            out << ",\"index_map\":[";
            for (std::size_t j = 0; j < result.index_map.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                out << result.index_map[j];
            }
            out << ']';
        }
        if (!result.vertices_path.empty()) {
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        } else {
            out << ",\"vertices\":[";
            for (std::size_t j = 0; j < result.vertices.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                write_vec3(out, result.vertices[j]);
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
                if (j > 0) {
                    out << ',';
                }
                out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
            }
            out << ']';
        }
        if (!result.normals_path.empty() && result.normals.size() == result.vertices.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (!result.uvs_path.empty() && result.uvs.size() == result.vertices.size()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        }
        if (!result.tangents_path.empty() && result.tangents.size() == result.vertices.size()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        }
        if (!result.tangent_signs_path.empty() && result.tangent_signs.size() == result.vertices.size()) {
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
        }
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
        out << '}';
    }
    out << "]}";
    return out.str();
}

struct MeshEditReportState {
    bool inline_sparse_delta = false;
    int changed_vertex_start = -1;
};

MeshEditReportState write_mesh_edit_result_geometry(
    std::ostream& out,
    const SubmeshMeshEditResult& result
) {
out << "{\"index\":" << result.index
    << ",\"action\":";
write_escaped(out, result.action);
if (result.resident_sparse) out << ",\"resident_sparse\":true";
if (result.append_submesh) {
    out << ",\"append_submesh\":true"
        << ",\"source_index\":" << result.source_index
        << ",\"name_suffix\":";
    write_escaped(out, result.name_suffix);
}
if (result.append_submesh || result.material_metadata_changed) {
    out << ",\"name\":";
    write_escaped(out, result.name);
    out << ",\"material\":";
    write_escaped(out, result.material);
    out << ",\"texture\":";
    write_escaped(out, result.texture);
    out << ",\"extra_attrs\":";
    if (result.extra_attrs.type == JsonValue::Type::Object) {
        write_json_value(out, result.extra_attrs);
    } else {
        out << "{}";
    }
}
out << ",\"topology_changed\":" << (result.topology_changed ? "true" : "false")
    << ",\"removed_faces\":" << result.removed_faces
    << ",\"removed_vertices\":" << result.removed_vertices
    << ",\"added_vertices\":" << result.added_vertices
    << ",\"added_faces\":" << result.added_faces;
if (result.suppress_vertex_remap_report) {
    out << ",\"vertex_remap_report_suppressed\":true";
}
const bool inline_sparse_delta = result.sparse
    && !result.topology_changed
    && result.changed_positions_path.empty()
    && result.changed_vertices.size() <= 256
    && result.changed_positions.size() == result.changed_vertices.size();
int changed_vertex_start = -1;
write_changed_vertices_report(
    out,
    result.changed_vertices,
    inline_sparse_delta ? std::string() : result.changed_vertices_path,
    changed_vertex_start
);
if (!result.before_positions.empty()
    && !result.before_positions_path.empty()
    && result.before_positions.size() == result.changed_vertices.size()) {
    if (inline_sparse_delta && result.sparse_snapshot_id.empty()) {
        out << ",\"before_positions\":[";
        for (std::size_t j = 0; j < result.before_positions.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            write_vec3(out, result.before_positions[j]);
        }
        out << ']';
    } else if (!inline_sparse_delta) {
        write_vec3_binary_file(result.before_positions_path, result.before_positions);
        out << ",\"before_positions_binary\":";
        write_vec3_binary_descriptor(out, result.before_positions_path, result.before_positions.size());
    }
}
if (!result.sparse_snapshot_id.empty() && result.before_positions.size() == result.changed_vertices.size()) {
    out << ",\"native_sparse_snapshot_id\":";
    write_escaped(out, result.sparse_snapshot_id);
}
if (result.sparse && !result.topology_changed) {
    if (!result.changed_positions_path.empty() && !inline_sparse_delta) {
        write_vec3_binary_file(result.changed_positions_path, result.changed_positions);
        out << ",\"changed_positions_binary\":";
        write_vec3_binary_descriptor(out, result.changed_positions_path, result.changed_positions.size());
    } else {
        out << ",\"changed_positions\":[";
        for (std::size_t j = 0; j < result.changed_positions.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            write_vec3(out, result.changed_positions[j]);
        }
        out << ']';
    }
} else {
    if (!result.vertices_path.empty()) {
        write_vec3_binary_file(result.vertices_path, result.vertices);
        out << ",\"vertices_binary\":";
        write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
    } else {
        out << ",\"vertices\":[";
        for (std::size_t j = 0; j < result.vertices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            write_vec3(out, result.vertices[j]);
        }
        out << ']';
    }
}
if (!result.faces.empty() && !result.faces_path.empty()) {
    write_faces_binary_file(result.faces_path, result.faces);
    out << ",\"faces_binary\":";
    write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
} else {
    out << ",\"faces\":[";
    for (std::size_t j = 0; j < result.faces.size(); ++j) {
        if (j > 0) {
            out << ',';
        }
        out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
    }
    out << ']';
}
    return {inline_sparse_delta, changed_vertex_start};
}

void write_mesh_edit_result_channels(std::ostream& out, const SubmeshMeshEditResult& result) {
if (!result.uvs_path.empty() && result.preview_uvs.size() == result.vertices.size()) {
    write_vec2_binary_file(result.uvs_path, result.preview_uvs);
    out << ",\"uvs_binary\":";
    write_vec2_binary_descriptor(out, result.uvs_path, result.preview_uvs.size());
}
if (result.topology_changed && !result.normals_path.empty() && result.normals.size() == result.vertices.size()) {
    write_vec3_binary_file(result.normals_path, result.normals);
    out << ",\"normals_binary\":";
    write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
}
if (result.topology_changed && !result.tangents_path.empty() && result.tangents.size() == result.vertices.size()) {
    write_vec3_binary_file(result.tangents_path, result.tangents);
    out << ",\"tangents_binary\":";
    write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
}
if (result.topology_changed && !result.tangent_signs_path.empty() && result.tangent_signs.size() == result.vertices.size()) {
    write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
    out << ",\"tangent_signs_binary\":";
    write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
}
const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
if (result.topology_changed
    && !result.bone_counts_path.empty()
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
if (result.topology_changed && !result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertices.size()) {
    int source_vertex_map_start = -1;
    if (contiguous_int_range(result.source_vertex_map, source_vertex_map_start)) {
        out << ",\"source_vertex_map_start\":" << source_vertex_map_start
            << ",\"source_vertex_map_count\":" << result.source_vertex_map.size();
    } else {
        write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
        out << ",\"source_vertex_map_binary\":";
        write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
    }
}
if (result.topology_changed && !result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertices.size()) {
    int source_vertex_offsets_start = -1;
    int source_vertex_offsets_stride = 0;
    if (contiguous_int_stride_range(result.source_vertex_offsets, source_vertex_offsets_start, source_vertex_offsets_stride)) {
        out << ",\"source_vertex_offsets_start\":" << source_vertex_offsets_start
            << ",\"source_vertex_offsets_count\":" << result.source_vertex_offsets.size()
            << ",\"source_vertex_offsets_stride\":" << source_vertex_offsets_stride;
    } else {
        write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
        out << ",\"source_vertex_offsets_binary\":";
        write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
    }
}
}

void write_mesh_edit_result_remap(std::ostream& out, const SubmeshMeshEditResult& result) {
if (!result.suppress_vertex_remap_report) {
    if (!result.copy_vertex_indices.empty() && !result.copy_vertex_indices_path.empty()) {
        write_int_binary_file(result.copy_vertex_indices_path, result.copy_vertex_indices);
        out << ",\"copy_vertex_indices_binary\":";
        write_int_binary_descriptor(out, result.copy_vertex_indices_path, result.copy_vertex_indices.size(), 1);
    } else {
        out << ",\"copy_vertex_indices\":[";
        for (std::size_t j = 0; j < result.copy_vertex_indices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << result.copy_vertex_indices[j];
        }
        out << ']';
    }
    if (!result.vertex_blends.empty() && !result.vertex_blend_indices_path.empty() && !result.vertex_blend_factors_path.empty()) {
        write_int_binary_file(result.vertex_blend_indices_path, flatten_vertex_blend_indices(result.vertex_blends));
        write_double_binary_file(result.vertex_blend_factors_path, flatten_vertex_blend_factors(result.vertex_blends));
        out << ",\"vertex_blend_indices_binary\":";
        write_int_binary_descriptor(out, result.vertex_blend_indices_path, result.vertex_blends.size(), 3);
        out << ",\"vertex_blend_factors_binary\":";
        write_f64_binary_descriptor(out, result.vertex_blend_factors_path, result.vertex_blends.size());
    } else {
        out << ",\"vertex_blends\":[";
        for (std::size_t j = 0; j < result.vertex_blends.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            const VertexBlend& blend = result.vertex_blends[j];
            out << "{\"index\":" << blend.index
                << ",\"left\":" << blend.left
                << ",\"right\":" << blend.right
                << ",\"factor\":" << std::setprecision(17) << blend.factor
                << '}';
        }
        out << ']';
    }
    if (!result.index_map.empty() && !result.index_map_path.empty()) {
        write_int_binary_file(result.index_map_path, result.index_map);
        out << ",\"index_map_binary\":";
        write_int_binary_descriptor(out, result.index_map_path, result.index_map.size(), 1);
    } else {
        out << ",\"index_map\":[";
        for (std::size_t j = 0; j < result.index_map.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << result.index_map[j];
        }
        out << ']';
    }
}

}

void write_mesh_edit_result_preview(
    std::ostream& out,
    const SubmeshMeshEditResult& result,
    bool include_preview_deltas,
    const MeshEditReportState& state
) {
if (include_preview_deltas && !result.topology_changed && !result.changed_vertices.empty()) {
    out << ",\"preview_vertex_update_group\":";
    if (result.sparse) {
        write_sparse_preview_vertex_update_group(
            out,
            result.index,
            result.changed_vertices,
            result.changed_positions,
            result.preview_normals,
            result.preview_uvs,
            state.inline_sparse_delta ? std::string() : result.changed_positions_path,
            state.changed_vertex_start,
            result.source_vertex_map,
            result.changed_source_vertex_ids
        );
    } else {
        write_preview_vertex_update_group(
            out,
            result.index,
            result.changed_vertices,
            result.vertices,
            result.preview_normals,
            result.preview_uvs,
            result.changed_vertices_path,
            result.source_vertex_map
        );
    }
}
if (include_preview_deltas && (result.topology_changed || result.material_metadata_changed || !result.faces.empty())) {
    const bool has_triangles = !result.vertices.empty() && !result.faces.empty();
    const std::vector<Vec3> preview_normals = has_triangles
        ? compute_smooth_normals(result.vertices, result.faces)
        : std::vector<Vec3>();
    out << ",\"preview_triangle_group\":";
    write_preview_triangle_group(
        out,
        result.index,
        result.vertices,
        result.faces,
        preview_normals,
        result.preview_uvs,
        result.preview_triangle_path,
        result.source_vertex_map,
        result.source_face_indices
    );
}
}

std::string mesh_edit_report_json(const std::vector<SubmeshMeshEditResult>& results, bool include_preview_deltas = true) {
    std::ostringstream out;
    bool topology_changed = false;
    std::string operation = "edit";
    for (const SubmeshMeshEditResult& result : results) {
        topology_changed = topology_changed || result.topology_changed;
        if (operation == "edit" && !result.action.empty()) {
            operation = result.action;
        }
    }
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, operation);
    out << ",\"topology_changed\":" << (topology_changed ? "true" : "false") << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const SubmeshMeshEditResult& result = results[i];
        const MeshEditReportState report_state = write_mesh_edit_result_geometry(out, result);
        write_mesh_edit_result_channels(out, result);
        write_mesh_edit_result_remap(out, result);
        write_mesh_edit_result_preview(out, result, include_preview_deltas, report_state);
        out << "}";
    }
    out << "]}";
    return out.str();
}

void write_optimization_stats(std::ostream& out, const OptimizationStats& stats) {
    out << "{\"cache_acmr\":" << std::setprecision(17) << stats.cache_acmr
        << ",\"cache_atvr\":" << stats.cache_atvr
        << ",\"overdraw\":" << stats.overdraw
        << ",\"overfetch\":" << stats.overfetch
        << '}';
}

std::string optimize_report_json(const std::vector<SubmeshOptimizeResult>& results) {
    std::ostringstream out;
    bool topology_changed = false;
    int input_indices = 0;
    int output_indices = 0;
    int input_triangles = 0;
    int output_triangles = 0;
    int input_vertices = 0;
    int referenced_vertices = 0;
    for (const SubmeshOptimizeResult& result : results) {
        topology_changed = topology_changed || result.topology_changed;
        input_indices += result.input_index_count;
        output_indices += result.output_index_count;
        input_triangles += result.input_triangle_count;
        output_triangles += result.output_triangle_count;
        input_vertices += result.input_vertex_count;
        referenced_vertices += result.referenced_vertex_count;
    }

    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"optimize\",\"optimization_backend\":\"meshoptimizer\""
        << ",\"topology_changed\":" << (topology_changed ? "true" : "false")
        << ",\"totals\":{\"input_vertex_count\":" << input_vertices
        << ",\"referenced_vertex_count\":" << referenced_vertices
        << ",\"input_index_count\":" << input_indices
        << ",\"output_index_count\":" << output_indices
        << ",\"input_triangle_count\":" << input_triangles
        << ",\"output_triangle_count\":" << output_triangles
        << "},\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const SubmeshOptimizeResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"optimization_backend\":\"meshoptimizer\""
            << ",\"input_vertex_count\":" << result.input_vertex_count
            << ",\"referenced_vertex_count\":" << result.referenced_vertex_count
            << ",\"fetch_vertex_count\":" << result.fetch_vertex_count
            << ",\"input_index_count\":" << result.input_index_count
            << ",\"output_index_count\":" << result.output_index_count
            << ",\"input_triangle_count\":" << result.input_triangle_count
            << ",\"output_triangle_count\":" << result.output_triangle_count
            << ",\"target_ratio\":" << std::setprecision(17) << result.target_ratio
            << ",\"target_error\":" << result.target_error
            << ",\"result_error\":" << result.result_error
            << ",\"simplified\":" << (result.simplified ? "true" : "false")
            << ",\"topology_changed\":" << (result.topology_changed ? "true" : "false")
            << ",\"before\":";
        write_optimization_stats(out, result.before);
        out << ",\"after\":";
        write_optimization_stats(out, result.after);
        out << ",\"faces\":[";
        for (std::size_t j = 0; j < result.faces.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
        }
        out << "]}";
    }
    out << "]}";
    return out.str();
}

std::string error_report_json(const std::string& message) {
    std::ostringstream out;
    out << "{\"status\":\"error\",\"backend\":\"cdmw_mesh_core_0.1\",\"message\":";
    write_escaped(out, message);
    out << '}';
    return out.str();
}

void append_i32_le(std::vector<char>& out, int value) {
    const std::int32_t raw = static_cast<std::int32_t>(value);
    out.push_back(static_cast<char>(raw & 0xff));
    out.push_back(static_cast<char>((raw >> 8) & 0xff));
    out.push_back(static_cast<char>((raw >> 16) & 0xff));
    out.push_back(static_cast<char>((raw >> 24) & 0xff));
}

std::string lower_ascii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}
