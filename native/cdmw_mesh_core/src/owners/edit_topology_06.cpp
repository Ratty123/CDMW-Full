void pack_weight_pairs_native(
    std::vector<std::pair<int, double>> pairs,
    int preferred_bone,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    std::vector<std::pair<int, double>> positive;
    positive.reserve(pairs.size());
    for (const auto& item : pairs) {
        if (item.first >= 0 && item.second > 0.0 && std::isfinite(item.second)) {
            positive.push_back(item);
        }
    }
    if (positive.empty()) {
        out_indices.clear();
        out_weights.clear();
        return;
    }
    if (positive.size() > 4) {
        std::vector<std::pair<int, double>> selected;
        for (const auto& item : positive) {
            if (item.first == preferred_bone) {
                selected.push_back(item);
                break;
            }
        }
        std::vector<std::pair<int, double>> others;
        for (const auto& item : positive) {
            if (item.first != preferred_bone) {
                others.push_back(item);
            }
        }
        std::sort(others.begin(), others.end(), [](const auto& left, const auto& right) {
            if (left.second != right.second) {
                return left.second > right.second;
            }
            return left.first < right.first;
        });
        for (const auto& item : others) {
            if (selected.size() >= 4) {
                break;
            }
            selected.push_back(item);
        }
        positive = std::move(selected);
    }
    double total = 0.0;
    for (const auto& item : positive) {
        total += item.second;
    }
    if (total <= 0.0 || !std::isfinite(total)) {
        out_indices.clear();
        out_weights.clear();
        return;
    }
    std::sort(positive.begin(), positive.end(), [](const auto& left, const auto& right) {
        return left.first < right.first;
    });
    out_indices.clear();
    out_weights.clear();
    out_indices.reserve(positive.size());
    out_weights.reserve(positive.size());
    for (const auto& item : positive) {
        out_indices.push_back(item.first);
        out_weights.push_back(item.second / total);
    }
}

void normalize_weight_row_native(
    const std::vector<int>& raw_indices,
    const std::vector<double>& raw_weights,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    pack_weight_pairs_native(clean_weight_pairs_native(raw_indices, raw_weights), -1, out_indices, out_weights);
}

void nudge_bone_weight_native(
    const std::vector<int>& raw_indices,
    const std::vector<double>& raw_weights,
    int bone_index,
    double delta,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    std::vector<std::pair<int, double>> pairs = clean_weight_pairs_native(raw_indices, raw_weights);
    double current = 0.0;
    std::vector<std::pair<int, double>> others;
    for (const auto& item : pairs) {
        if (item.first == bone_index) {
            current += item.second;
        } else {
            others.push_back(item);
        }
    }
    const double target = std::max(0.0, std::min(1.0, current + delta));
    if (target > 0.0) {
        double other_total = 0.0;
        for (const auto& item : others) {
            other_total += item.second;
        }
        if (other_total > 0.0 && std::isfinite(other_total)) {
            const double scale = (1.0 - target) / other_total;
            for (auto& item : others) {
                item.second *= scale;
            }
            others.push_back({bone_index, target});
            pairs = std::move(others);
        } else {
            pairs = {{bone_index, 1.0}};
        }
    } else {
        pairs = std::move(others);
    }
    pack_weight_pairs_native(std::move(pairs), bone_index, out_indices, out_weights);
}

std::vector<int> optional_source_vertex_map_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (!bool_or(item.get("source_vertex_map_is_donor_lineage"), true)) {
        return {};
    }
    if (item.get("source_vertex_map_binary") != nullptr
        || item.get("source_vertex_map") != nullptr
        || item.get("source_vertex_map_start") != nullptr) {
        const std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_vertex_map_binary",
            "source_vertex_map",
            "source_vertex_map_start",
            "source_vertex_map_count"
        );
        if (values.size() == vertex_count) {
            return values;
        }
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_vertex_map.size() == vertex_count) {
            return session->source_vertex_map;
        }
    }
    return {};
}

BoneAssignments source_bone_assignments_from_item(const JsonValue& item) {
    BoneAssignments result;
    if (item.get("source_bone_counts_binary") == nullptr
        || item.get("source_bone_indices_binary") == nullptr
        || item.get("source_bone_weights_binary") == nullptr) {
        return result;
    }
    const std::vector<int> counts = int_vector_from_binary_or_json(item, "source_bone_counts_binary", "source_bone_counts");
    const std::vector<int> flat_indices = int_vector_from_binary_or_json(item, "source_bone_indices_binary", "source_bone_indices_flat");
    const std::vector<double> flat_weights = double_vector_from_binary_or_json(item, "source_bone_weights_binary", "source_bone_weights_flat");
    if (flat_indices.size() != flat_weights.size()) {
        return {};
    }
    std::size_t flat_offset = 0;
    result.indices.reserve(counts.size());
    result.weights.reserve(counts.size());
    for (const int raw_count : counts) {
        if (raw_count < 0) {
            return {};
        }
        const std::size_t count = static_cast<std::size_t>(raw_count);
        if (flat_offset + count > flat_indices.size()) {
            return {};
        }
        std::vector<int> indices;
        std::vector<double> weights;
        indices.reserve(count);
        weights.reserve(count);
        for (std::size_t index = 0; index < count; ++index) {
            const int bone = flat_indices[flat_offset + index];
            const double weight = flat_weights[flat_offset + index];
            if (bone < 0 || !std::isfinite(weight)) {
                return {};
            }
            indices.push_back(bone);
            weights.push_back(weight);
        }
        result.indices.push_back(std::move(indices));
        result.weights.push_back(std::move(weights));
        flat_offset += count;
    }
    if (flat_offset != flat_indices.size()) {
        return {};
    }
    return result;
}

std::map<int, int> bone_remap_from_item(const JsonValue& item) {
    const std::vector<int> source = int_vector_from_binary_or_json(item, "bone_remap_source_binary", "bone_remap_source");
    const std::vector<int> target = int_vector_from_binary_or_json(item, "bone_remap_target_binary", "bone_remap_target");
    std::map<int, int> remap;
    const std::size_t count = std::min(source.size(), target.size());
    for (std::size_t index = 0; index < count; ++index) {
        if (source[index] >= 0 && target[index] >= 0) {
            remap[source[index]] = target[index];
        }
    }
    return remap;
}

int nearest_source_vertex_index_native(const Vec3& target, const std::vector<Vec3>& source_vertices) {
    int best_index = -1;
    double best_distance = std::numeric_limits<double>::infinity();
    for (std::size_t index = 0; index < source_vertices.size(); ++index) {
        const double distance = distance_squared_vec3(target, source_vertices[index]);
        if (distance < best_distance) {
            best_distance = distance;
            best_index = static_cast<int>(index);
        }
    }
    return best_index;
}

std::string suffixed_output_path(const std::string& path, const std::string& suffix) {
    return path.empty() ? path : path + suffix;
}

void transfer_weight_row_native(
    const std::vector<int>& source_indices,
    const std::vector<double>& source_weights,
    bool remap_enabled,
    const std::map<int, int>& bone_remap,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    std::vector<std::pair<int, double>> pairs = clean_weight_pairs_native(source_indices, source_weights);
    if (remap_enabled) {
        std::vector<std::pair<int, double>> remapped;
        remapped.reserve(pairs.size());
        for (const auto& item : pairs) {
            const auto found = bone_remap.find(item.first);
            if (found != bone_remap.end()) {
                remapped.push_back({found->second, item.second});
            }
        }
        pairs = std::move(remapped);
    }
    pack_weight_pairs_native(std::move(pairs), -1, out_indices, out_weights);
}

std::vector<int> source_vertex_values_for_result(
    const JsonValue& item,
    const SubmeshMeshEditResult& result,
    const std::string& binary_key,
    const std::string& json_key,
    int default_value
) {
    std::vector<int> input = binary_key == "source_vertex_offsets_binary"
        ? source_vertex_offsets_from_item(item)
        : binary_key == "source_vertex_map_binary"
        ? int_vector_from_binary_or_json(
            item,
            binary_key,
            json_key,
            "source_vertex_map_start",
            "source_vertex_map_count"
        )
        : int_vector_from_binary_or_json(item, binary_key, json_key);
    if (input.empty()) {
        if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
            if (binary_key == "source_vertex_map_binary") {
                input = session->source_vertex_map;
            } else if (binary_key == "source_vertex_offsets_binary") {
                input = session->source_vertex_offsets;
            }
        }
    }
    if (input.empty()) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<int> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.size()) {
            output.push_back(input[static_cast<std::size_t>(source_index)]);
            continue;
        }
        if (blends.find(static_cast<int>(index)) != blends.end()) {
            output.push_back(default_value);
            continue;
        }
        return {};
    }
    return output;
}

std::vector<SubmeshMeshEditResult> run_mesh_edit_operation(
    const JsonValue& item,
    const JsonValue& edit,
    const std::string& operation,
    const MeshEditorScreenBrushDepthMask* shared_depth_mask = nullptr
) {
std::vector<SubmeshMeshEditResult> item_results;
if (operation == "brush") {
    item_results.push_back(run_brush_edit_for_submesh(item, edit, shared_depth_mask));
} else if (operation == "delete") {
    item_results.push_back(run_delete_edit_for_submesh(item, edit));
} else if (operation == "dissolve") {
    item_results.push_back(run_dissolve_edit_for_submesh(item));
} else if (operation == "extrude") {
    item_results.push_back(run_extrude_edit_for_submesh(item, edit));
} else if (operation == "inset") {
    item_results.push_back(run_inset_edit_for_submesh(item, edit));
} else if (operation == "compact_orphans") {
    item_results.push_back(run_compact_orphans_for_submesh(item));
} else if (operation == "split") {
    item_results.push_back(run_split_edit_for_submesh(item));
} else if (operation == "duplicate") {
    item_results.push_back(run_duplicate_edit_for_submesh(item));
} else if (operation == "mirror") {
    item_results.push_back(run_mirror_edit_for_submesh(item, edit));
} else if (operation == "separate") {
    item_results = run_separate_edit_for_submesh(item);
} else if (operation == "fix_winding") {
    item_results.push_back(run_fix_winding_edit_for_submesh(item));
} else if (operation == "fill_holes") {
    item_results.push_back(run_fill_holes_edit_for_submesh(item));
} else if (operation == "fill") {
    item_results.push_back(run_fill_edit_for_submesh(item));
} else if (operation == "loop_cut") {
    item_results.push_back(run_loop_cut_edit_for_submesh(item, edit));
} else if (operation == "edge_split") {
    item_results.push_back(run_edge_split_edit_for_submesh(item));
} else if (operation == "merge") {
    item_results.push_back(run_merge_edit_for_submesh(item));
} else if (operation == "weld") {
    item_results.push_back(run_weld_edit_for_submesh(item, edit));
} else if (operation == "triangulate_display") {
    item_results.push_back(run_triangulate_display_edit_for_submesh(item));
} else if (operation == "bridge") {
    item_results.push_back(run_bridge_edit_for_submesh(item));
} else if (operation == "subdivide") {
    item_results.push_back(run_subdivide_edit_for_submesh(item, edit, false));
} else if (operation == "refine_smooth") {
    item_results.push_back(run_subdivide_edit_for_submesh(item, edit, true));
} else {
    throw std::runtime_error("unsupported mesh edit operation: " + operation);
}
    return item_results;
}

void set_mesh_edit_result_output_paths(
    SubmeshMeshEditResult& result,
    const JsonValue& item,
    const JsonValue& edit
) {
    result.changed_positions_path = string_or(item.get("changed_positions_output_path"), "");
    result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
    result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
    result.vertices_path = string_or(item.get("vertices_output_path"), "");
    result.faces_path = string_or(item.get("faces_output_path"), "");
    result.normals_path = string_or(item.get("normals_output_path"), "");
    result.uvs_path = string_or(item.get("uvs_output_path"), "");
    result.tangents_path = string_or(item.get("tangents_output_path"), "");
    result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
    result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
    result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
    result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
    result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
    result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
    result.preview_triangle_path = string_or(item.get("preview_triangle_output_path"), "");
    result.copy_vertex_indices_path = string_or(item.get("copy_vertex_indices_output_path"), "");
    result.vertex_blend_indices_path = string_or(item.get("vertex_blend_indices_output_path"), "");
    result.vertex_blend_factors_path = string_or(item.get("vertex_blend_factors_output_path"), "");
    result.index_map_path = string_or(item.get("index_map_output_path"), "");
    result.suppress_vertex_remap_report = bool_or(
        item.get("suppress_vertex_remap_report"),
        bool_or(edit.get("suppress_vertex_remap_report"), false)
    );
}

void prepare_appended_mesh_edit_result(
    SubmeshMeshEditResult& result,
    const JsonValue& item
) {
    if (!result.append_submesh) {
        return;
    }
    const std::string source_name = string_or(item.get("name"), "");
    const std::string base_name = source_name.empty()
        ? std::string("part_") + std::to_string(result.source_index >= 0 ? result.source_index : result.index)
        : source_name;
    if (result.name.empty()) {
        result.name = base_name + result.name_suffix;
    }
    if (result.material.empty()) {
        result.material = string_or(item.get("material"), "");
    }
    if (result.texture.empty()) {
        result.texture = string_or(item.get("texture"), "");
    }
    if (result.extra_attrs.type != JsonValue::Type::Object) {
        if (const JsonValue* extra_attrs = item.get("extra_attrs")) {
            if (extra_attrs->type == JsonValue::Type::Object) {
                result.extra_attrs = *extra_attrs;
            }
        }
    }
    const std::string suffix = ".append";
    result.changed_positions_path = suffixed_output_path(result.changed_positions_path, suffix);
    result.before_positions_path = suffixed_output_path(result.before_positions_path, suffix);
    result.changed_vertices_path = suffixed_output_path(result.changed_vertices_path, suffix);
    result.vertices_path = suffixed_output_path(result.vertices_path, suffix);
    result.faces_path = suffixed_output_path(result.faces_path, suffix);
    result.normals_path = suffixed_output_path(result.normals_path, suffix);
    result.uvs_path = suffixed_output_path(result.uvs_path, suffix);
    result.tangents_path = suffixed_output_path(result.tangents_path, suffix);
    result.tangent_signs_path = suffixed_output_path(result.tangent_signs_path, suffix);
    result.bone_counts_path = suffixed_output_path(result.bone_counts_path, suffix);
    result.bone_indices_path = suffixed_output_path(result.bone_indices_path, suffix);
    result.bone_weights_path = suffixed_output_path(result.bone_weights_path, suffix);
    result.source_vertex_map_path = suffixed_output_path(result.source_vertex_map_path, suffix);
    result.source_vertex_offsets_path = suffixed_output_path(result.source_vertex_offsets_path, suffix);
    result.preview_triangle_path = suffixed_output_path(result.preview_triangle_path, suffix);
    result.copy_vertex_indices_path = suffixed_output_path(result.copy_vertex_indices_path, suffix);
    result.vertex_blend_indices_path = suffixed_output_path(result.vertex_blend_indices_path, suffix);
    result.vertex_blend_factors_path = suffixed_output_path(result.vertex_blend_factors_path, suffix);
    result.index_map_path = suffixed_output_path(result.index_map_path, suffix);
}

std::vector<SubmeshMeshEditResult> run_mesh_edit(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    const JsonValue* edit = root.get("edit");
    if (edit == nullptr || edit->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing edit object");
    }
    std::string operation = string_or(edit->get("operation"), string_or(root.get("operation"), ""));
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    MeshEditorScreenBrushDepthMask shared_depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* shared_depth_mask = nullptr;
    if (operation == "brush") {
        const JsonValue* raw_screen_brush = edit->get("screen_brush");
        for (const JsonValue& item : submeshes->array_value) {
            if (item.type != JsonValue::Type::Object) continue;
            shared_depth_mask = mesh_editor_screen_brush_depth_mask_for_edit(
                item,
                *edit,
                raw_screen_brush,
                shared_depth_mask_storage
            );
            break;
        }
    }
    std::vector<SubmeshMeshEditResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        std::vector<SubmeshMeshEditResult> item_results = run_mesh_edit_operation(
            item,
            *edit,
            operation,
            shared_depth_mask
        );
        for (SubmeshMeshEditResult& result : item_results) {
            set_mesh_edit_result_output_paths(result, item, *edit);
            prepare_appended_mesh_edit_result(result, item);
            if (result.index >= 0 && (result.topology_changed || !result.vertices.empty() || !result.faces.empty() || !result.changed_vertices.empty())) {
                if (result.topology_changed) {
                    if (!result.normals_path.empty()) {
                        result.normals = vec3_values_for_result(mesh_normals_from_item(item), result);
                    }
                    result.preview_uvs = preview_uvs_for_result(item, result);
                    result.tangents = vec3_values_for_result(mesh_tangents_from_item(item), result);
                    result.tangent_signs = double_values_for_result(mesh_tangent_signs_from_item(item), result);
                    if (result.mirror_axis_index >= 0) {
                        for (Vec3& normal : result.normals) {
                            normal = mirrored_vec3_axis(normal, result.mirror_axis_index);
                        }
                        for (Vec3& tangent : result.tangents) {
                            tangent = mirrored_vec3_axis(tangent, result.mirror_axis_index);
                        }
                    }
                    result.bones = bone_values_for_result(mesh_bones_from_item(item), result);
                    result.source_vertex_map = source_vertex_values_for_result(
                        item,
                        result,
                        "source_vertex_map_binary",
                        "source_vertex_map",
                        -1
                    );
                    result.source_vertex_offsets = source_vertex_values_for_result(
                        item,
                        result,
                        "source_vertex_offsets_binary",
                        "source_vertex_offsets",
                        -1
                    );
                    if (result.source_face_indices.size() != result.faces.size()) {
                        result.source_face_indices = identity_indices(result.faces.size());
                    }
                } else if (!result.changed_vertices.empty()) {
                    result.preview_uvs = preview_uvs_for_result(item, result);
                    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, result.vertices.size());
                    if (!faces.empty()) {
                        result.preview_normals = compute_smooth_normals(result.vertices, faces);
                    }
                    result.sparse_snapshot_id = sparse_snapshot_id;
                    store_sparse_vertex_snapshot_values(
                        sparse_snapshot_id,
                        result.index,
                        static_cast<int>(result.vertices.size()),
                        result.changed_vertices,
                        result.before_positions
                    );
                }
                if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
                    if (result.topology_changed && !result.append_submesh) {
                        session->vertices = result.vertices;
                        session->faces = result.faces;
                        session->source_face_indices = result.source_face_indices.size() == result.faces.size()
                            ? result.source_face_indices
                            : identity_indices(session->faces.size());
                        session->normals = result.normals.size() == result.vertices.size() ? result.normals : std::vector<Vec3>();
                        session->uvs = result.preview_uvs.size() == result.vertices.size() ? result.preview_uvs : std::vector<Vec2>();
                        session->tangents = result.tangents.size() == result.vertices.size() ? result.tangents : std::vector<Vec3>();
                        session->tangent_signs = result.tangent_signs.size() == result.vertices.size() ? result.tangent_signs : std::vector<double>();
                        if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
                            session->bone_indices = result.bones.indices;
                            session->bone_weights = result.bones.weights;
                        } else {
                            session->bone_indices.clear();
                            session->bone_weights.clear();
                        }
                        session->source_vertex_map = result.source_vertex_map.size() == result.vertices.size() ? result.source_vertex_map : std::vector<int>();
                        session->source_vertex_offsets = result.source_vertex_offsets.size() == result.vertices.size() ? result.source_vertex_offsets : std::vector<int>();
                    } else if (!result.topology_changed && session->vertices.size() == result.vertices.size()) {
                        session->vertices = result.vertices;
                        session->normals.clear();
                    }
                }
                results.push_back(std::move(result));
            }
        }
    }
    return results;
}

int count_degenerate_uv_faces(
    const std::vector<Vec2>& uvs,
    const std::vector<std::array<int, 3>>& faces
) {
    int count = 0;
    for (const auto& face : faces) {
        const Vec2 uv0 = uvs[static_cast<std::size_t>(face[0])];
        const Vec2 uv1 = uvs[static_cast<std::size_t>(face[1])];
        const Vec2 uv2 = uvs[static_cast<std::size_t>(face[2])];
        const double du1 = uv1[0] - uv0[0];
        const double dv1 = uv1[1] - uv0[1];
        const double du2 = uv2[0] - uv0[0];
        const double dv2 = uv2[1] - uv0[1];
        const double denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) <= 1e-12 || !std::isfinite(denom)) {
            ++count;
        }
    }
    return count;
}

void update_tangent_storage_safety(TangentBuildResult& build, std::size_t vertex_count) {
    std::vector<bool> seen(vertex_count, false);
    std::vector<Vec3> first_tangents(vertex_count, {1.0, 0.0, 0.0});
    std::vector<double> first_signs(vertex_count, 1.0);
    std::set<int> split_required;
    for (const FaceCornerTangents& face_corners : build.face_corner_tangents) {
        for (std::size_t corner = 0; corner < face_corners.vertices.size(); ++corner) {
            const int index = face_corners.vertices[corner];
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
                continue;
            }
            const std::size_t vertex_index = static_cast<std::size_t>(index);
            if (!seen[vertex_index]) {
                seen[vertex_index] = true;
                first_tangents[vertex_index] = face_corners.tangents[corner];
                first_signs[vertex_index] = face_corners.signs[corner];
                continue;
            }
            if (!same_vec3(first_tangents[vertex_index], face_corners.tangents[corner])
                || std::abs(first_signs[vertex_index] - face_corners.signs[corner]) > 1e-8) {
                split_required.insert(index);
            }
        }
    }
    build.vertex_signs = std::move(first_signs);
    build.split_required_vertices.assign(split_required.begin(), split_required.end());
    build.vertex_storage_safe = build.split_required_vertices.empty();
}

TangentBuildResult compute_tangent_basis_fallback(
    const std::vector<Vec3>& vertices,
    const std::vector<Vec2>& uvs,
    const std::vector<Vec3>& normals,
    const std::vector<std::array<int, 3>>& faces
) {
    TangentBuildResult build;
    std::vector<Vec3> accum(vertices.size(), {0.0, 0.0, 0.0});
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const auto& face = faces[face_index];
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const Vec3 edge1 = sub_vec3(vertices[static_cast<std::size_t>(b)], vertices[static_cast<std::size_t>(a)]);
        const Vec3 edge2 = sub_vec3(vertices[static_cast<std::size_t>(c)], vertices[static_cast<std::size_t>(a)]);
        const Vec2 uv0 = uvs[static_cast<std::size_t>(a)];
        const Vec2 uv1 = uvs[static_cast<std::size_t>(b)];
        const Vec2 uv2 = uvs[static_cast<std::size_t>(c)];
        const double du1 = uv1[0] - uv0[0];
        const double dv1 = uv1[1] - uv0[1];
        const double du2 = uv2[0] - uv0[0];
        const double dv2 = uv2[1] - uv0[1];
        const double denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) <= 1e-12 || !std::isfinite(denom)) {
            ++build.degenerate_uv_faces;
            continue;
        }
        const Vec3 tangent = scale_vec3(sub_vec3(scale_vec3(edge1, dv2), scale_vec3(edge2, dv1)), 1.0 / denom);
        const Vec3 bitangent = scale_vec3(sub_vec3(scale_vec3(edge2, du1), scale_vec3(edge1, du2)), 1.0 / denom);
        FaceCornerTangents face_corners;
        face_corners.face_index = static_cast<int>(face_index);
        face_corners.vertices = face;
        for (int corner = 0; corner < 3; ++corner) {
            const int index = face[static_cast<std::size_t>(corner)];
            const Vec3 normal = normals.size() == vertices.size() ? normals[static_cast<std::size_t>(index)] : Vec3{0.0, 0.0, 1.0};
            const Vec3 projected = sub_vec3(tangent, scale_vec3(normal, dot_vec3(normal, tangent)));
            const Vec3 normalized_tangent = normalized_vec3(projected, {1.0, 0.0, 0.0});
            face_corners.tangents[static_cast<std::size_t>(corner)] = normalized_tangent;
            const Vec3 cross{
                normal[1] * normalized_tangent[2] - normal[2] * normalized_tangent[1],
                normal[2] * normalized_tangent[0] - normal[0] * normalized_tangent[2],
                normal[0] * normalized_tangent[1] - normal[1] * normalized_tangent[0],
            };
            face_corners.signs[static_cast<std::size_t>(corner)] = dot_vec3(cross, bitangent) < 0.0 ? -1.0 : 1.0;
            accum[static_cast<std::size_t>(index)] = add_vec3(accum[static_cast<std::size_t>(index)], tangent);
            ++build.face_corner_tangent_count;
        }
        build.face_corner_tangents.push_back(face_corners);
    }

    build.vertex_tangents.reserve(vertices.size());
    for (std::size_t index = 0; index < accum.size(); ++index) {
        const Vec3 normal = normals.size() == vertices.size() ? normals[index] : Vec3{0.0, 0.0, 1.0};
        const Vec3 projected = sub_vec3(accum[index], scale_vec3(normal, dot_vec3(normal, accum[index])));
        build.vertex_tangents.push_back(normalized_vec3(projected, {1.0, 0.0, 0.0}));
    }
    update_tangent_storage_safety(build, vertices.size());
    return build;
}

struct MikkTangentContextData {
    const std::vector<Vec3>* vertices = nullptr;
    const std::vector<Vec2>* uvs = nullptr;
    const std::vector<Vec3>* normals = nullptr;
    const std::vector<std::array<int, 3>>* faces = nullptr;
    std::vector<FaceCornerTangents>* face_corner_tangents = nullptr;
    int face_corner_tangent_count = 0;
};

MikkTangentContextData* mikk_data(const SMikkTSpaceContext* context) {
    return static_cast<MikkTangentContextData*>(context->m_pUserData);
}

int mikk_get_num_faces(const SMikkTSpaceContext* context) {
    const MikkTangentContextData* data = mikk_data(context);
    return data && data->faces ? static_cast<int>(data->faces->size()) : 0;
}

int mikk_get_num_vertices_of_face(const SMikkTSpaceContext*, const int) {
    return 3;
}

void mikk_get_position(const SMikkTSpaceContext* context, float out[], const int face_index, const int vertex_index) {
    const MikkTangentContextData* data = mikk_data(context);
    const int index = (*data->faces)[static_cast<std::size_t>(face_index)][static_cast<std::size_t>(vertex_index)];
    const Vec3& value = (*data->vertices)[static_cast<std::size_t>(index)];
    out[0] = static_cast<float>(value[0]);
    out[1] = static_cast<float>(value[1]);
    out[2] = static_cast<float>(value[2]);
}

void mikk_get_normal(const SMikkTSpaceContext* context, float out[], const int face_index, const int vertex_index) {
    const MikkTangentContextData* data = mikk_data(context);
    const int index = (*data->faces)[static_cast<std::size_t>(face_index)][static_cast<std::size_t>(vertex_index)];
    const Vec3 normal = normalized_vec3((*data->normals)[static_cast<std::size_t>(index)], {0.0, 0.0, 1.0});
    out[0] = static_cast<float>(normal[0]);
    out[1] = static_cast<float>(normal[1]);
    out[2] = static_cast<float>(normal[2]);
}

void mikk_get_tex_coord(const SMikkTSpaceContext* context, float out[], const int face_index, const int vertex_index) {
    const MikkTangentContextData* data = mikk_data(context);
    const int index = (*data->faces)[static_cast<std::size_t>(face_index)][static_cast<std::size_t>(vertex_index)];
    const Vec2& value = (*data->uvs)[static_cast<std::size_t>(index)];
    out[0] = static_cast<float>(value[0]);
    out[1] = static_cast<float>(value[1]);
}

void mikk_set_tspace_basic(
    const SMikkTSpaceContext* context,
    const float tangent[],
    const float sign,
    const int face_index,
    const int vertex_index
) {
    MikkTangentContextData* data = mikk_data(context);
    if (data == nullptr || data->face_corner_tangents == nullptr) {
        return;
    }
    if (face_index < 0 || vertex_index < 0 || vertex_index >= 3 || static_cast<std::size_t>(face_index) >= data->face_corner_tangents->size()) {
        return;
    }
    FaceCornerTangents& face_corners = (*data->face_corner_tangents)[static_cast<std::size_t>(face_index)];
    face_corners.tangents[static_cast<std::size_t>(vertex_index)] = normalized_vec3(
        {static_cast<double>(tangent[0]), static_cast<double>(tangent[1]), static_cast<double>(tangent[2])},
        {1.0, 0.0, 0.0}
    );
    face_corners.signs[static_cast<std::size_t>(vertex_index)] = sign >= 0.0f ? 1.0 : -1.0;
    ++data->face_corner_tangent_count;
}

TangentBuildResult compute_tangent_basis(
    const std::vector<Vec3>& vertices,
    const std::vector<Vec2>& uvs,
    const std::vector<Vec3>& normals,
    const std::vector<std::array<int, 3>>& faces
) {
    TangentBuildResult build;
    build.tangent_backend = "mikktspace_reference";
    build.degenerate_uv_faces = count_degenerate_uv_faces(uvs, faces);
    build.face_corner_tangents.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        FaceCornerTangents face_corners;
        face_corners.face_index = static_cast<int>(face_index);
        face_corners.vertices = faces[face_index];
        build.face_corner_tangents.push_back(face_corners);
    }

    MikkTangentContextData data;
    data.vertices = &vertices;
    data.uvs = &uvs;
    data.normals = &normals;
    data.faces = &faces;
    data.face_corner_tangents = &build.face_corner_tangents;

    SMikkTSpaceInterface interface_callbacks = {};
    interface_callbacks.m_getNumFaces = mikk_get_num_faces;
    interface_callbacks.m_getNumVerticesOfFace = mikk_get_num_vertices_of_face;
    interface_callbacks.m_getPosition = mikk_get_position;
    interface_callbacks.m_getNormal = mikk_get_normal;
    interface_callbacks.m_getTexCoord = mikk_get_tex_coord;
    interface_callbacks.m_setTSpaceBasic = mikk_set_tspace_basic;

    SMikkTSpaceContext context = {};
    context.m_pInterface = &interface_callbacks;
    context.m_pUserData = &data;

    if (!genTangSpaceDefault(&context)) {
        return compute_tangent_basis_fallback(vertices, uvs, normals, faces);
    }

    build.face_corner_tangent_count = data.face_corner_tangent_count;
    std::vector<Vec3> accum(vertices.size(), {0.0, 0.0, 0.0});
    std::vector<int> counts(vertices.size(), 0);
    for (const FaceCornerTangents& face_corners : build.face_corner_tangents) {
        for (std::size_t corner = 0; corner < face_corners.vertices.size(); ++corner) {
            const int index = face_corners.vertices[corner];
            if (0 <= index && static_cast<std::size_t>(index) < accum.size()) {
                accum[static_cast<std::size_t>(index)] = add_vec3(accum[static_cast<std::size_t>(index)], face_corners.tangents[corner]);
                ++counts[static_cast<std::size_t>(index)];
            }
        }
    }
    build.vertex_tangents.reserve(vertices.size());
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        build.vertex_tangents.push_back(
            counts[index] > 0 ? normalized_vec3(accum[index], {1.0, 0.0, 0.0}) : Vec3{1.0, 0.0, 0.0}
        );
    }
    update_tangent_storage_safety(build, vertices.size());
    return build;
}
