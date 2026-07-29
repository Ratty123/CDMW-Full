struct NativeWeightTransferSample {
    std::vector<int> indices;
    std::vector<double> weights;
    double distance = std::numeric_limits<double>::infinity();
    bool valid = false;
};

struct ClosestTrianglePointNative {
    std::array<double, 3> barycentric{1.0, 0.0, 0.0};
    double distance_squared = std::numeric_limits<double>::infinity();
};

ClosestTrianglePointNative closest_triangle_point_native(
    const Vec3& point,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c
) {
    const Vec3 ab = sub_vec3(b, a);
    const Vec3 ac = sub_vec3(c, a);
    const Vec3 ap = sub_vec3(point, a);
    const double d1 = dot_vec3(ab, ap);
    const double d2 = dot_vec3(ac, ap);
    if (d1 <= 0.0 && d2 <= 0.0) {
        return {{1.0, 0.0, 0.0}, dot_vec3(ap, ap)};
    }
    const Vec3 bp = sub_vec3(point, b);
    const double d3 = dot_vec3(ab, bp);
    const double d4 = dot_vec3(ac, bp);
    if (d3 >= 0.0 && d4 <= d3) {
        return {{0.0, 1.0, 0.0}, dot_vec3(bp, bp)};
    }
    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) {
        const double v = d1 / (d1 - d3);
        const Vec3 closest = add_vec3(a, scale_vec3(ab, v));
        return {{1.0 - v, v, 0.0}, distance_squared_vec3(point, closest)};
    }
    const Vec3 cp = sub_vec3(point, c);
    const double d5 = dot_vec3(ab, cp);
    const double d6 = dot_vec3(ac, cp);
    if (d6 >= 0.0 && d5 <= d6) {
        return {{0.0, 0.0, 1.0}, dot_vec3(cp, cp)};
    }
    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0) {
        const double w = d2 / (d2 - d6);
        const Vec3 closest = add_vec3(a, scale_vec3(ac, w));
        return {{1.0 - w, 0.0, w}, distance_squared_vec3(point, closest)};
    }
    const double va = d3 * d6 - d5 * d4;
    if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0) {
        const Vec3 edge = sub_vec3(c, b);
        const double w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        const Vec3 closest = add_vec3(b, scale_vec3(edge, w));
        return {{0.0, 1.0 - w, w}, distance_squared_vec3(point, closest)};
    }
    const double denominator = va + vb + vc;
    if (std::fabs(denominator) <= 1.0e-20) {
        return {{1.0, 0.0, 0.0}, dot_vec3(ap, ap)};
    }
    const double v = vb / denominator;
    const double w = vc / denominator;
    const Vec3 closest = add_vec3(a, add_vec3(scale_vec3(ab, v), scale_vec3(ac, w)));
    return {{1.0 - v - w, v, w}, distance_squared_vec3(point, closest)};
}

NativeWeightTransferSample closest_source_weight_sample_native(
    const Vec3& target,
    const std::vector<Vec3>& source_vertices,
    const std::vector<std::array<int, 3>>& source_faces,
    const BoneAssignments& source_bones,
    bool remap_enabled,
    const std::map<int, int>& bone_remap
) {
    ClosestTrianglePointNative closest;
    std::array<int, 3> closest_face{-1, -1, -1};
    for (const auto& face : source_faces) {
        if (face[0] < 0 || face[1] < 0 || face[2] < 0
            || static_cast<std::size_t>(face[0]) >= source_vertices.size()
            || static_cast<std::size_t>(face[1]) >= source_vertices.size()
            || static_cast<std::size_t>(face[2]) >= source_vertices.size()) {
            continue;
        }
        const ClosestTrianglePointNative candidate = closest_triangle_point_native(
            target,
            source_vertices[static_cast<std::size_t>(face[0])],
            source_vertices[static_cast<std::size_t>(face[1])],
            source_vertices[static_cast<std::size_t>(face[2])]
        );
        if (candidate.distance_squared < closest.distance_squared) {
            closest = candidate;
            closest_face = face;
        }
    }
    if (closest_face[0] < 0) {
        const int source_index = nearest_source_vertex_index_native(target, source_vertices);
        NativeWeightTransferSample sample;
        if (source_index < 0 || static_cast<std::size_t>(source_index) >= source_bones.indices.size()) {
            return sample;
        }
        transfer_weight_row_native(
            source_bones.indices[static_cast<std::size_t>(source_index)],
            source_bones.weights[static_cast<std::size_t>(source_index)],
            remap_enabled,
            bone_remap,
            sample.indices,
            sample.weights
        );
        sample.distance = std::sqrt(distance_squared_vec3(target, source_vertices[static_cast<std::size_t>(source_index)]));
        sample.valid = !sample.indices.empty() && sample.indices.size() == sample.weights.size();
        return sample;
    }
    std::map<int, double> blended;
    for (std::size_t corner = 0; corner < 3; ++corner) {
        const double blend = closest.barycentric[corner];
        if (blend <= 1.0e-12) {
            continue;
        }
        const std::size_t source_index = static_cast<std::size_t>(closest_face[corner]);
        const auto pairs = clean_weight_pairs_native(source_bones.indices[source_index], source_bones.weights[source_index]);
        if (pairs.empty()) {
            return {};
        }
        for (const auto& item : pairs) {
            int bone_index = item.first;
            if (remap_enabled) {
                const auto found = bone_remap.find(bone_index);
                if (found == bone_remap.end()) {
                    continue;
                }
                bone_index = found->second;
            }
            blended[bone_index] += blend * item.second;
        }
    }
    NativeWeightTransferSample sample;
    std::vector<std::pair<int, double>> pairs(blended.begin(), blended.end());
    pack_weight_pairs_native(std::move(pairs), -1, sample.indices, sample.weights);
    sample.distance = std::sqrt(std::max(0.0, closest.distance_squared));
    sample.valid = !sample.indices.empty() && sample.indices.size() == sample.weights.size();
    return sample;
}

bool refit_triangle_corners_native(
    const std::map<int, std::vector<Vec3>>& positions,
    int submesh_index,
    const std::array<int, 3>& corners,
    std::array<Vec3, 3>& out
) {
    const auto found = positions.find(submesh_index);
    if (found == positions.end()) return false;
    for (std::size_t corner = 0; corner < 3; ++corner) {
        const int vertex_index = corners[corner];
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= found->second.size()) return false;
        out[corner] = found->second[static_cast<std::size_t>(vertex_index)];
    }
    return true;
}

Vec3 refit_face_normal_native(const Vec3& a, const Vec3& b, const Vec3& c) {
    const Vec3 ab = sub_vec3(b, a);
    const Vec3 ac = sub_vec3(c, a);
    const Vec3 normal{
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    };
    const double length_squared = dot_vec3(normal, normal);
    // Judge the cross product against the edges that produced it rather than
    // against an absolute epsilon, so a millimetre-scale but well-formed face
    // survives while a sliver at any scale does not.
    const double edge_scale = dot_vec3(ab, ab) * dot_vec3(ac, ac);
    if (!std::isfinite(length_squared) || length_squared <= edge_scale * 1.0e-16) {
        return Vec3{0.0, 0.0, 0.0};
    }
    return scale_vec3(normal, 1.0 / std::sqrt(length_squared));
}

bool refit_barycentric_point_native(
    const MeshRefitVertexBindingRuntime& binding,
    const std::map<int, std::vector<Vec3>>& positions,
    Vec3& out
) {
    std::array<Vec3, 3> triangle{};
    if (!refit_triangle_corners_native(positions, binding.driver_submesh_index, binding.driver_vertices, triangle)) {
        return false;
    }
    out = Vec3{0.0, 0.0, 0.0};
    for (std::size_t corner = 0; corner < 3; ++corner) {
        out = add_vec3(out, scale_vec3(triangle[corner], binding.barycentric[corner]));
    }
    return true;
}

Vec3 refit_binding_face_normal_native(
    const MeshRefitVertexBindingRuntime& binding,
    const std::map<int, std::vector<Vec3>>& positions
) {
    std::array<Vec3, 3> triangle{};
    if (!refit_triangle_corners_native(positions, binding.driver_submesh_index, binding.driver_vertices, triangle)) {
        return Vec3{0.0, 0.0, 0.0};
    }
    return refit_face_normal_native(triangle[0], triangle[1], triangle[2]);
}

void refit_bind_normal_height_native(
    MeshRefitVertexBindingRuntime& binding,
    const std::map<int, std::vector<Vec3>>& baseline,
    const Vec3& garment_rest
) {
    binding.baseline_normal = Vec3{0.0, 0.0, 0.0};
    binding.normal_height = 0.0;
    Vec3 point{0.0, 0.0, 0.0};
    const Vec3 normal = refit_binding_face_normal_native(binding, baseline);
    if (dot_vec3(normal, normal) <= 0.0 || !refit_barycentric_point_native(binding, baseline, point)) return;
    binding.baseline_normal = normal;
    binding.normal_height = dot_vec3(sub_vec3(garment_rest, point), normal);
}

Vec3 refit_normal_correction_native(
    const MeshRefitVertexBindingRuntime& binding,
    const std::map<int, std::vector<Vec3>>& current
) {
    if (dot_vec3(binding.baseline_normal, binding.baseline_normal) <= 0.0) return Vec3{0.0, 0.0, 0.0};
    const Vec3 normal = refit_binding_face_normal_native(binding, current);
    // A face that collapses only under the live morph keeps the rest standoff
    // rather than snapping the vertex onto the driver surface.
    if (dot_vec3(normal, normal) <= 0.0) return Vec3{0.0, 0.0, 0.0};
    return scale_vec3(sub_vec3(normal, binding.baseline_normal), binding.normal_height);
}

double skin_transfer_distance_limit_native(const std::vector<Vec3>& vertices) {
    if (vertices.empty()) {
        return 0.0;
    }
    Vec3 minimum = vertices.front();
    Vec3 maximum = vertices.front();
    for (const Vec3& vertex : vertices) {
        for (std::size_t axis = 0; axis < 3; ++axis) {
            minimum[axis] = std::min(minimum[axis], vertex[axis]);
            maximum[axis] = std::max(maximum[axis], vertex[axis]);
        }
    }
    return std::max(1.0e-8, length_vec3(sub_vec3(maximum, minimum)) * 0.05);
}

double percentile_95_native(std::vector<double> values) {
    values.erase(std::remove_if(values.begin(), values.end(), [](double value) {
        return !std::isfinite(value) || value < 0.0;
    }), values.end());
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const std::size_t rank = std::max<std::size_t>(1, static_cast<std::size_t>(std::ceil(values.size() * 0.95)));
    return values[std::min(values.size() - 1, rank - 1)];
}

void refit_rebind_bindings_native(
    MeshRefitRuntime& refit,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    // Rebasing moves the rest state onto the current geometry, so everything the
    // bindings measured against the old rest has to be measured again: the
    // standoff each vertex keeps from its face, and the distances the status
    // line reports as current. Leaving the standoff behind would re-apply an
    // already-baked rotation on the next slider move; leaving the distances
    // behind would describe a rest state that no longer exists, so the warning
    // could stay lit after a bake had resolved it, or stay dark after an edit
    // had pulled a garment away from its driver. The bound face and
    // barycentrics are deliberately kept: this re-measures the existing
    // bindings, it does not re-bind them.
    std::vector<Vec3> driver_vertices;
    for (const auto& item : refit.driver_baseline_positions) {
        driver_vertices.insert(driver_vertices.end(), item.second.begin(), item.second.end());
    }
    std::vector<double> distances;
    distances.reserve(refit.bindings.size());
    for (MeshRefitVertexBindingRuntime& binding : refit.bindings) {
        const auto garment = submeshes.find(binding.garment_submesh_index);
        Vec3 point{0.0, 0.0, 0.0};
        if (garment == submeshes.end()
            || binding.garment_vertex_index < 0
            || static_cast<std::size_t>(binding.garment_vertex_index) >= garment->second.vertices.size()
            || !refit_barycentric_point_native(binding, refit.driver_baseline_positions, point)) {
            binding.baseline_normal = Vec3{0.0, 0.0, 0.0};
            binding.normal_height = 0.0;
            continue;
        }
        const Vec3& rest = garment->second.vertices[static_cast<std::size_t>(binding.garment_vertex_index)];
        refit_bind_normal_height_native(binding, refit.driver_baseline_positions, rest);
        binding.distance = length_vec3(sub_vec3(rest, point));
        distances.push_back(binding.distance);
    }
    refit.warning_distance = skin_transfer_distance_limit_native(driver_vertices);
    refit.maximum_distance = distances.empty()
        ? 0.0
        : *std::max_element(distances.begin(), distances.end());
    refit.p95_distance = percentile_95_native(distances);
    refit.distance_warning = refit.maximum_distance > refit.warning_distance
        || refit.p95_distance > refit.warning_distance;
}
