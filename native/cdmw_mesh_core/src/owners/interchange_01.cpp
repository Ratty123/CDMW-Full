PoseMatrix4 pose_identity_matrix() {
    return {
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
}
PoseMatrix4 pose_transpose_matrix(const PoseMatrix4& matrix) {
    PoseMatrix4 result{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            result[static_cast<std::size_t>(row * 4 + column)] =
                matrix[static_cast<std::size_t>(column * 4 + row)];
        }
    }
    return result;
}
bool pose_matrix4_from_json(const JsonValue* value, PoseMatrix4& out) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() != 16) {
        return false;
    }
    bool nonzero = false;
    PoseMatrix4 matrix{};
    for (std::size_t index = 0; index < 16; ++index) {
        const JsonValue& raw = value->array_value[index];
        if (raw.type != JsonValue::Type::Number || !std::isfinite(raw.number_value)) {
            return false;
        }
        matrix[index] = raw.number_value;
        nonzero = nonzero || std::fabs(raw.number_value) > 1e-12;
    }
    if (!nonzero) {
        return false;
    }
    const double column_translation = std::fabs(matrix[3]) + std::fabs(matrix[7]) + std::fabs(matrix[11]);
    const double row_translation = std::fabs(matrix[12]) + std::fabs(matrix[13]) + std::fabs(matrix[14]);
    out = row_translation > column_translation && column_translation <= 1e-6
        ? pose_transpose_matrix(matrix)
        : matrix;
    return true;
}

PoseMatrix4 pose_translation_matrix(const Vec3& position) {
    return {
        1.0, 0.0, 0.0, position[0],
        0.0, 1.0, 0.0, position[1],
        0.0, 0.0, 1.0, position[2],
        0.0, 0.0, 0.0, 1.0,
    };
}

PoseMatrix4 pose_matrix_multiply(const PoseMatrix4& left, const PoseMatrix4& right) {
    PoseMatrix4 result{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            double value = 0.0;
            for (int mid = 0; mid < 4; ++mid) {
                value += left[static_cast<std::size_t>(row * 4 + mid)]
                    * right[static_cast<std::size_t>(mid * 4 + column)];
            }
            result[static_cast<std::size_t>(row * 4 + column)] = value;
        }
    }
    return result;
}

PoseMatrix4 pose_invert_rigid_affine(const PoseMatrix4& matrix) {
    const double r00 = matrix[0], r01 = matrix[1], r02 = matrix[2], tx = matrix[3];
    const double r10 = matrix[4], r11 = matrix[5], r12 = matrix[6], ty = matrix[7];
    const double r20 = matrix[8], r21 = matrix[9], r22 = matrix[10], tz = matrix[11];
    return {
        r00, r10, r20, -(r00 * tx + r10 * ty + r20 * tz),
        r01, r11, r21, -(r01 * tx + r11 * ty + r21 * tz),
        r02, r12, r22, -(r02 * tx + r12 * ty + r22 * tz),
        0.0, 0.0, 0.0, 1.0,
    };
}

PoseMatrix4 pose_euler_rotation_matrix(const Vec3& rotation_degrees) {
    constexpr double pi = 3.141592653589793238462643383279502884;
    const double x = rotation_degrees[0] * pi / 180.0;
    const double y = rotation_degrees[1] * pi / 180.0;
    const double z = rotation_degrees[2] * pi / 180.0;
    const double cx = std::cos(x), sx = std::sin(x);
    const double cy = std::cos(y), sy = std::sin(y);
    const double cz = std::cos(z), sz = std::sin(z);
    const PoseMatrix4 rx = {
        1.0, 0.0, 0.0, 0.0,
        0.0, cx, -sx, 0.0,
        0.0, sx, cx, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    const PoseMatrix4 ry = {
        cy, 0.0, sy, 0.0,
        0.0, 1.0, 0.0, 0.0,
        -sy, 0.0, cy, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    const PoseMatrix4 rz = {
        cz, -sz, 0.0, 0.0,
        sz, cz, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    return pose_matrix_multiply(rz, pose_matrix_multiply(ry, rx));
}

Vec3 pose_transform_point(const PoseMatrix4& matrix, const Vec3& point) {
    const double x = point[0], y = point[1], z = point[2];
    return {
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    };
}

std::vector<NativePoseBone> pose_bones_from_json(const JsonValue* value) {
    std::vector<NativePoseBone> bones;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return bones;
    }
    bones.reserve(value->array_value.size());
    for (std::size_t ordinal = 0; ordinal < value->array_value.size(); ++ordinal) {
        const JsonValue& item = value->array_value[ordinal];
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        NativePoseBone bone;
        bone.index = int_or(item.get("index"), static_cast<int>(ordinal));
        if (bone.index < 0) {
            bone.index = static_cast<int>(ordinal);
        }
        bone.parent_index = int_or(item.get("parent_index"), -1);
        bone.position = vec3_or(item.get("position"), Vec3{0.0, 0.0, 0.0});
        bone.has_bind_matrix = pose_matrix4_from_json(item.get("bind_matrix"), bone.bind_matrix);
        bone.has_inv_bind_matrix = pose_matrix4_from_json(item.get("inv_bind_matrix"), bone.inv_bind_matrix);
        bones.push_back(bone);
    }
    return bones;
}

std::map<int, Vec3> pose_rotations_from_json(const JsonValue* value) {
    std::map<int, Vec3> rotations;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return rotations;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("bone_index"), int_or(item.get("index"), -1));
        if (index < 0) {
            continue;
        }
        const Vec3 rotation = vec3_or(item.get("rotation_degrees"), Vec3{0.0, 0.0, 0.0});
        if (std::fabs(rotation[0]) <= 1e-6 && std::fabs(rotation[1]) <= 1e-6 && std::fabs(rotation[2]) <= 1e-6) {
            continue;
        }
        rotations[index] = rotation;
    }
    return rotations;
}

std::map<int, PoseMatrix4> pose_skinning_matrices(
    const std::vector<NativePoseBone>& raw_bones,
    const std::map<int, Vec3>& rotations
) {
    std::map<int, NativePoseBone> bones;
    for (std::size_t ordinal = 0; ordinal < raw_bones.size(); ++ordinal) {
        NativePoseBone bone = raw_bones[ordinal];
        if (bone.index < 0) {
            bone.index = static_cast<int>(ordinal);
        }
        bones[bone.index] = bone;
    }
    std::map<int, PoseMatrix4> bind_globals;
    std::map<int, PoseMatrix4> pose_globals;
    std::map<int, PoseMatrix4> skinning;
    const PoseMatrix4 identity = pose_identity_matrix();

    std::function<void(int, std::set<int>)> build = [&](int index, std::set<int> seen) {
        if (skinning.find(index) != skinning.end()) {
            return;
        }
        const auto bone_found = bones.find(index);
        if (bone_found == bones.end()) {
            return;
        }
        if (seen.find(index) != seen.end()) {
            bind_globals[index] = identity;
            pose_globals[index] = identity;
            skinning[index] = identity;
            return;
        }
        seen.insert(index);
        const NativePoseBone& bone = bone_found->second;
        int parent_index = bone.parent_index;
        if (parent_index == index || bones.find(parent_index) == bones.end()) {
            parent_index = -1;
        }
        if (parent_index >= 0) {
            build(parent_index, seen);
        }
        const PoseMatrix4 bind_global = bone.has_bind_matrix
            ? bone.bind_matrix
            : pose_translation_matrix(bone.position);
        bind_globals[index] = bind_global;
        PoseMatrix4 local_bind = bind_global;
        PoseMatrix4 parent_pose = identity;
        if (parent_index >= 0) {
            const PoseMatrix4 parent_bind_inverse = pose_invert_rigid_affine(bind_globals[parent_index]);
            local_bind = pose_matrix_multiply(parent_bind_inverse, bind_global);
            parent_pose = pose_globals[parent_index];
        }
        Vec3 rotation{0.0, 0.0, 0.0};
        const auto rotation_found = rotations.find(index);
        if (rotation_found != rotations.end()) {
            rotation = rotation_found->second;
        }
        const PoseMatrix4 pose_local = pose_matrix_multiply(local_bind, pose_euler_rotation_matrix(rotation));
        const PoseMatrix4 pose_global = pose_matrix_multiply(parent_pose, pose_local);
        pose_globals[index] = pose_global;
        const PoseMatrix4 inv_bind = bone.has_inv_bind_matrix ? bone.inv_bind_matrix : pose_invert_rigid_affine(bind_global);
        skinning[index] = pose_matrix_multiply(pose_global, inv_bind);
    };

    for (const auto& item : bones) {
        build(item.first, {});
    }
    return skinning;
}

Vec3 pose_skin_vertex(
    const Vec3& vertex,
    const std::vector<int>& bone_indices,
    const std::vector<double>& bone_weights,
    const std::map<int, PoseMatrix4>& skinning_matrices
) {
    if (bone_indices.size() != bone_weights.size()) {
        return vertex;
    }
    double total = 0.0;
    Vec3 result{0.0, 0.0, 0.0};
    for (std::size_t index = 0; index < bone_indices.size(); ++index) {
        const int bone_index = bone_indices[index];
        const double weight = bone_weights[index];
        if (bone_index < 0 || !std::isfinite(weight) || weight <= 0.0) {
            continue;
        }
        const auto matrix_found = skinning_matrices.find(bone_index);
        if (matrix_found == skinning_matrices.end()) {
            continue;
        }
        const Vec3 posed = pose_transform_point(matrix_found->second, vertex);
        result[0] += posed[0] * weight;
        result[1] += posed[1] * weight;
        result[2] += posed[2] * weight;
        total += weight;
    }
    if (total <= 1e-8) {
        return vertex;
    }
    return {result[0] / total, result[1] / total, result[2] / total};
}

std::vector<SubmeshPosePreviewResult> run_pose_preview(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::vector<NativePoseBone> bones = pose_bones_from_json(root.get("bones"));
    const std::map<int, Vec3> rotations = pose_rotations_from_json(root.get("rotations"));
    if (bones.empty() || rotations.empty()) {
        return {};
    }
    const std::map<int, PoseMatrix4> skinning = pose_skinning_matrices(bones, rotations);
    if (skinning.empty()) {
        return {};
    }

    std::vector<SubmeshPosePreviewResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshPosePreviewResult result;
        result.index = int_or(item.get("index"), static_cast<int>(results.size()));
        if (result.index < 0) {
            continue;
        }
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        result.vertex_count = static_cast<int>(vertices.size());
        if (result.vertex_count <= 0) {
            continue;
        }
        const BoneAssignments assignments = mesh_bones_from_item(item);
        if (!valid_bone_assignments(assignments)
            || assignments.indices.size() != vertices.size()
            || assignments.weights.size() != vertices.size()) {
            continue;
        }
        result.vertices.reserve(vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
            const Vec3 posed = pose_skin_vertex(
                vertices[vertex_index],
                assignments.indices[vertex_index],
                assignments.weights[vertex_index],
                skinning
            );
            result.vertices.push_back(posed);
            if (std::fabs(posed[0] - vertices[vertex_index][0]) > 1e-6
                || std::fabs(posed[1] - vertices[vertex_index][1]) > 1e-6
                || std::fabs(posed[2] - vertices[vertex_index][2]) > 1e-6) {
                result.changed_vertices.push_back(static_cast<int>(vertex_index));
            }
        }
        if (!result.changed_vertices.empty()) {
            results.push_back(std::move(result));
        }
    }
    return results;
}
std::vector<SubmeshSkinWeightsResult> run_skin_weights(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string operation = string_or(root.get("operation"), "normalize");
    const int bone_index = int_or(root.get("bone_index"), -1);
    const double delta = number_or(root.get("delta"), 0.0);
    if (operation == "adjust" && (bone_index < 0 || !std::isfinite(delta))) {
        throw std::runtime_error("invalid skin weight adjust parameters");
    }
    if (operation != "adjust" && operation != "normalize" && operation != "transfer") {
        throw std::runtime_error("unsupported skin weight operation");
    }
    std::vector<SubmeshSkinWeightsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshSkinWeightsResult result;
        result.index = int_or(item.get("index"), static_cast<int>(results.size()));
        if (result.index < 0) {
            continue;
        }
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.vertex_count = static_cast<int>(mesh_vertex_count_from_item(item));
        if (result.vertex_count <= 0) {
            continue;
        }
        BoneAssignments bones = mesh_bones_from_item(item);
        if (!valid_bone_assignments(bones) || bones.indices.size() != static_cast<std::size_t>(result.vertex_count)) {
            bones.indices.assign(static_cast<std::size_t>(result.vertex_count), {});
            bones.weights.assign(static_cast<std::size_t>(result.vertex_count), {});
        }
        std::set<int> selected_set = selected_vertices_from_binary_or_json(item, static_cast<std::size_t>(result.vertex_count));
        std::vector<int> selected_vertices(selected_set.begin(), selected_set.end());
        const std::vector<Vec3> target_vertices = operation == "transfer" ? mesh_vertices_from_item(item) : std::vector<Vec3>();
        const std::vector<Vec3> source_vertices = operation == "transfer"
            ? vertices_from_binary_or_json(item, "source_vertices_binary", "source_vertices")
            : std::vector<Vec3>();
        const std::vector<std::array<int, 3>> source_faces = operation == "transfer"
            ? faces_from_binary_or_json_keys(item, "source_faces_binary", "source_faces", source_vertices.size())
            : std::vector<std::array<int, 3>>();
        BoneAssignments source_bones = operation == "transfer" ? source_bone_assignments_from_item(item) : BoneAssignments();
        if (operation == "transfer" && (!valid_bone_assignments(source_bones) || source_bones.indices.size() != source_vertices.size())) {
            continue;
        }
        const std::vector<int> source_vertex_map = operation == "transfer"
            ? optional_source_vertex_map_from_item(item, static_cast<std::size_t>(result.vertex_count))
            : std::vector<int>();
        const bool remap_enabled = operation == "transfer" && bool_or(item.get("bone_remap_enabled"), false);
        const std::map<int, int> bone_remap = operation == "transfer" ? bone_remap_from_item(item) : std::map<int, int>();
        std::vector<double> spatial_transfer_distances;
        for (const int vertex_index : selected_vertices) {
            if (vertex_index < 0 || vertex_index >= result.vertex_count) {
                continue;
            }
            const std::size_t row = static_cast<std::size_t>(vertex_index);
            std::vector<int> next_indices;
            std::vector<double> next_weights;
            if (operation == "adjust") {
                nudge_bone_weight_native(bones.indices[row], bones.weights[row], bone_index, delta, next_indices, next_weights);
            } else if (operation == "normalize") {
                normalize_weight_row_native(bones.indices[row], bones.weights[row], next_indices, next_weights);
            } else {
                int source_index = -1;
                if (source_vertex_map.size() == static_cast<std::size_t>(result.vertex_count)) {
                    const int mapped = source_vertex_map[row];
                    if (mapped >= 0 && static_cast<std::size_t>(mapped) < source_vertices.size()) {
                        source_index = mapped;
                    }
                }
                if (source_index < 0
                    && target_vertices.size() == static_cast<std::size_t>(result.vertex_count)
                    && !source_vertices.empty()) {
                    const NativeWeightTransferSample sample = closest_source_weight_sample_native(
                        target_vertices[row],
                        source_vertices,
                        source_faces,
                        source_bones,
                        remap_enabled,
                        bone_remap
                    );
                    if (!sample.valid) {
                        throw std::runtime_error("source skin weight row is empty or invalid");
                    }
                    next_indices = sample.indices;
                    next_weights = sample.weights;
                    spatial_transfer_distances.push_back(sample.distance);
                }
                if (source_index >= 0) {
                    if (static_cast<std::size_t>(source_index) >= source_bones.indices.size()) {
                        continue;
                    }
                    transfer_weight_row_native(
                        source_bones.indices[static_cast<std::size_t>(source_index)],
                        source_bones.weights[static_cast<std::size_t>(source_index)],
                        remap_enabled,
                        bone_remap,
                        next_indices,
                        next_weights
                    );
                }
                if (next_indices.empty() || next_indices.size() != next_weights.size()) {
                    throw std::runtime_error("source skin weight row is empty or invalid");
                }
            }
            if (next_indices == bones.indices[row] && next_weights == bones.weights[row]) {
                continue;
            }
            bones.indices[row] = std::move(next_indices);
            bones.weights[row] = std::move(next_weights);
            result.changed_vertices.push_back(vertex_index);
        }
        if (operation == "transfer") {
            result.transfer_distance_p95 = percentile_95_native(spatial_transfer_distances);
            result.transfer_distance_limit = skin_transfer_distance_limit_native(source_vertices);
            result.transfer_distance_warning = !spatial_transfer_distances.empty()
                && result.transfer_distance_p95 > result.transfer_distance_limit;
        }
        if (result.changed_vertices.empty()) {
            continue;
        }
        result.bones = std::move(bones);
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            session->bone_indices = result.bones.indices;
            session->bone_weights = result.bones.weights;
        }
        const std::vector<int> counts = bone_assignment_counts(result.bones);
        const std::vector<int> flat_indices = flatten_bone_indices(result.bones);
        const std::vector<double> flat_weights = flatten_bone_weights(result.bones);
        if (counts.size() != result.bones.indices.size() || flat_indices.size() != flat_weights.size()) {
            throw std::runtime_error("invalid skin weight output");
        }
        write_int_binary_file(result.bone_counts_path, counts);
        write_int_binary_file(result.bone_indices_path, flat_indices);
        write_double_binary_file(result.bone_weights_path, flat_weights);
        results.push_back(std::move(result));
    }
    return results;
}
ObjRoundtripManifestSubmesh obj_manifest_submesh_from_item(
    const JsonValue& item,
    int fallback_index,
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces
) {
    const int index = int_or(item.get("index"), fallback_index);
    ObjRoundtripManifestSubmesh result;
    result.index = index;
    result.name = string_or(item.get("name"), std::string("part_") + std::to_string(index));
    result.material = string_or(item.get("material"), result.name);
    result.texture = string_or(item.get("texture"), "");
    result.vertex_count = static_cast<int>(vertices.size());
    result.face_count = static_cast<int>(faces.size());
    result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());
    return result;
}

void write_obj_roundtrip_manifest(
    const std::string& manifest_path,
    const std::string& source_path,
    const std::string& source_format,
    const std::string& export_path,
    const std::string& companion_path,
    const std::vector<ObjRoundtripManifestSubmesh>& submeshes,
    const JsonValue* extra_payload
);

ObjExportResult run_obj_export(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("missing output_path");
    }
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string base_name = string_or(root.get("base_name"), "mesh");
    const std::string source_path = string_or(root.get("source_path"), "");
    const std::string source_format = string_or(root.get("source_format"), "");
    const std::string mtl_filename = string_or(root.get("mtl_filename"), "");
    const double scale = number_or(root.get("scale"), 1.0);
    if (!std::isfinite(scale)) {
        throw std::runtime_error("non-finite OBJ export scale");
    }

    std::ofstream out(output_path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("cannot open OBJ output file: " + output_path);
    }

    int total_vertices = int_or(root.get("total_vertices"), 0);
    int total_faces = int_or(root.get("total_faces"), 0);
    if (total_vertices < 0) {
        total_vertices = 0;
    }
    if (total_faces < 0) {
        total_faces = 0;
    }

    out << "# Crimson Desert Mesh - " << base_name << "\n"
        << "# " << submeshes->array_value.size() << " submesh(es), "
        << total_vertices << " verts, " << total_faces << " faces\n"
        << "# Exported by Crimson Desert Mod Workbench\n"
        << "# source_path: " << source_path << "\n"
        << "# source_format: " << source_format << "\n";
    if (!mtl_filename.empty()) {
        out << "mtllib " << mtl_filename << "\n";
    }
    out << "\n";

    int vertex_offset = 1;
    int uv_offset = 1;
    int normal_offset = 1;
    ObjExportResult result;
    result.output_path = output_path;
    result.manifest_path = string_or(root.get("manifest_output_path"), "");
    std::vector<ObjRoundtripManifestSubmesh> manifest_submeshes;

    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), result.submesh_count);
        const std::string name = string_or(item.get("name"), std::string("part_") + std::to_string(index));
        const std::string material = string_or(item.get("material"), name);
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        manifest_submeshes.push_back(obj_manifest_submesh_from_item(item, index, vertices, faces));

        out << "o " << name << "\n";
        out << "usemtl " << material << "\n";
        out << std::defaultfloat << std::setprecision(17);
        for (const Vec3& vertex : vertices) {
            out << "v " << vertex[0] * scale << ' ' << vertex[1] * scale << ' ' << vertex[2] * scale << "\n";
        }
        for (const Vec2& uv : uvs) {
            out << "vt " << uv[0] << ' ' << (1.0 - uv[1]) << "\n";
        }
        out << std::defaultfloat << std::setprecision(17);
        for (const Vec3& normal : normals) {
            out << "vn " << normal[0] << ' ' << normal[1] << ' ' << normal[2] << "\n";
        }
        out << "s 1\n";

        const bool has_uv = !uvs.empty();
        const bool has_normals = !normals.empty();
        for (const std::array<int, 3>& face : faces) {
            const int va = face[0] + vertex_offset;
            const int vb = face[1] + vertex_offset;
            const int vc = face[2] + vertex_offset;
            if (has_uv && has_normals) {
                const int ta = face[0] + uv_offset;
                const int tb = face[1] + uv_offset;
                const int tc = face[2] + uv_offset;
                const int na = face[0] + normal_offset;
                const int nb = face[1] + normal_offset;
                const int nc = face[2] + normal_offset;
                out << "f " << va << '/' << ta << '/' << na << ' '
                    << vb << '/' << tb << '/' << nb << ' '
                    << vc << '/' << tc << '/' << nc << "\n";
            } else if (has_uv) {
                const int ta = face[0] + uv_offset;
                const int tb = face[1] + uv_offset;
                const int tc = face[2] + uv_offset;
                out << "f " << va << '/' << ta << ' ' << vb << '/' << tb << ' ' << vc << '/' << tc << "\n";
            } else if (has_normals) {
                const int na = face[0] + normal_offset;
                const int nb = face[1] + normal_offset;
                const int nc = face[2] + normal_offset;
                out << "f " << va << "//" << na << ' ' << vb << "//" << nb << ' ' << vc << "//" << nc << "\n";
            } else {
                out << "f " << va << ' ' << vb << ' ' << vc << "\n";
            }
        }
        out << "\n";
        vertex_offset += static_cast<int>(vertices.size());
        uv_offset += static_cast<int>(uvs.size());
        normal_offset += static_cast<int>(normals.size());
        result.vertex_count += static_cast<int>(vertices.size());
        result.face_count += static_cast<int>(faces.size());
        ++result.submesh_count;
    }

    if (!out) {
        throw std::runtime_error("cannot write OBJ output file: " + output_path);
    }
    if (!result.manifest_path.empty()) {
        write_obj_roundtrip_manifest(
            result.manifest_path,
            source_path,
            source_format,
            string_or(root.get("export_path"), output_path),
            mtl_filename,
            manifest_submeshes,
            root.get("extra_payload")
        );
    }
    return result;
}

ObjManifestResult run_obj_manifest(const JsonValue& root) {
    const std::string manifest_path = string_or(root.get("manifest_output_path"), "");
    if (manifest_path.empty()) {
        throw std::runtime_error("missing manifest_output_path");
    }
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<ObjRoundtripManifestSubmesh> manifest_submeshes;
    ObjManifestResult result;
    result.manifest_path = manifest_path;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), static_cast<int>(manifest_submeshes.size()));
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        manifest_submeshes.push_back(obj_manifest_submesh_from_item(item, index, vertices, faces));
        result.vertex_count += static_cast<int>(vertices.size());
        result.face_count += static_cast<int>(faces.size());
        ++result.submesh_count;
    }
    write_obj_roundtrip_manifest(
        manifest_path,
        string_or(root.get("source_path"), ""),
        string_or(root.get("source_format"), ""),
        string_or(root.get("export_path"), ""),
        string_or(root.get("companion_path"), string_or(root.get("companion_filename"), "")),
        manifest_submeshes,
        root.get("extra_payload")
    );
    return result;
}

std::vector<double> flatten_fbx_vertices(const std::vector<Vec3>& vertices, double scale) {
    std::vector<double> result;
    result.reserve(vertices.size() * 3);
    for (const Vec3& vertex : vertices) {
        result.push_back(vertex[0] * scale);
        result.push_back(vertex[1] * scale);
        result.push_back(vertex[2] * scale);
    }
    return result;
}

std::vector<int> flatten_fbx_polygon_indices(const std::vector<std::array<int, 3>>& faces) {
    std::vector<int> result;
    result.reserve(faces.size() * 3);
    for (const std::array<int, 3>& face : faces) {
        result.push_back(face[0]);
        result.push_back(face[1]);
        result.push_back(face[2] ^ -1);
    }
    return result;
}

std::vector<double> flatten_fbx_normals(const std::vector<Vec3>& normals) {
    std::vector<double> result;
    result.reserve(normals.size() * 3);
    for (const Vec3& normal : normals) {
        result.push_back(normal[0]);
        result.push_back(normal[1]);
        result.push_back(normal[2]);
    }
    return result;
}

std::vector<double> flatten_fbx_uvs(const std::vector<Vec2>& uvs) {
    std::vector<double> result;
    result.reserve(uvs.size() * 2);
    for (const Vec2& uv : uvs) {
        result.push_back(uv[0]);
        result.push_back(1.0 - uv[1]);
    }
    return result;
}

std::vector<FbxGeometrySubmeshResult> run_fbx_geometry(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const double scale = number_or(root.get("scale"), 1.0);
    if (!std::isfinite(scale)) {
        throw std::runtime_error("non-finite FBX geometry scale");
    }
    const bool require_vertex_aligned_uvs = bool_or(root.get("require_vertex_aligned_uvs"), false);
    std::vector<FbxGeometrySubmeshResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        FbxGeometrySubmeshResult result;
        result.index = int_or(item.get("index"), static_cast<int>(results.size()));
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.indices_path = string_or(item.get("indices_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        if (result.vertices_path.empty() || result.indices_path.empty() || result.normals_path.empty() || result.uvs_path.empty()) {
            throw std::runtime_error("missing FBX geometry output path");
        }

        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (require_vertex_aligned_uvs && uvs.size() != vertices.size()) {
            uvs.clear();
        }

        const std::vector<double> flat_vertices = flatten_fbx_vertices(vertices, scale);
        const std::vector<int> flat_indices = flatten_fbx_polygon_indices(faces);
        const std::vector<double> flat_normals = flatten_fbx_normals(normals);
        const std::vector<double> flat_uvs = flatten_fbx_uvs(uvs);

        write_double_binary_file(result.vertices_path, flat_vertices);
        write_int_binary_file(result.indices_path, flat_indices);
        write_double_binary_file(result.normals_path, flat_normals);
        write_double_binary_file(result.uvs_path, flat_uvs);

        result.vertex_count = static_cast<int>(vertices.size());
        result.face_count = static_cast<int>(faces.size());
        result.normal_count = static_cast<int>(normals.size());
        result.uv_count = static_cast<int>(uvs.size());
        result.vertex_value_count = flat_vertices.size();
        result.index_value_count = flat_indices.size();
        result.normal_value_count = flat_normals.size();
        result.uv_value_count = flat_uvs.size();
        results.push_back(std::move(result));
    }
    return results;
}

struct NativeFbxProperty {
    enum class Kind { Int32, Int64, Double, String, DoubleArray, IntArray };

    Kind kind = Kind::Int32;
    int int_value = 0;
    long long long_value = 0;
    double double_value = 0.0;
    std::string string_value;
    std::vector<double> double_values;
    std::vector<int> int_values;
};

NativeFbxProperty fbx_i32(int value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::Int32;
    prop.int_value = value;
    return prop;
}

NativeFbxProperty fbx_i64(long long value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::Int64;
    prop.long_value = value;
    return prop;
}

NativeFbxProperty fbx_f64(double value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::Double;
    prop.double_value = value;
    return prop;
}
