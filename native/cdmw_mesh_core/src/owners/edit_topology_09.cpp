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

struct RefitSpatialTriangleNative {
    int driver_submesh_index = -1;
    std::array<int, 3> driver_vertices{-1, -1, -1};
    std::array<Vec3, 3> corners{};
    Vec3 minimum{0.0, 0.0, 0.0};
    Vec3 maximum{0.0, 0.0, 0.0};
    Vec3 centroid{0.0, 0.0, 0.0};
    std::size_t source_order = 0;
};

struct RefitSpatialNodeNative {
    Vec3 minimum{0.0, 0.0, 0.0};
    Vec3 maximum{0.0, 0.0, 0.0};
    std::size_t begin = 0;
    std::size_t end = 0;
    int left = -1;
    int right = -1;
};

struct RefitSpatialIndexNative {
    std::vector<RefitSpatialTriangleNative> triangles;
    std::vector<std::size_t> triangle_order;
    std::vector<RefitSpatialNodeNative> nodes;
    int root = -1;
};

double refit_aabb_distance_squared_native(
    const Vec3& point,
    const Vec3& minimum,
    const Vec3& maximum
) {
    double result = 0.0;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const double delta = point[axis] < minimum[axis]
            ? minimum[axis] - point[axis]
            : point[axis] > maximum[axis]
                ? point[axis] - maximum[axis]
                : 0.0;
        result += delta * delta;
    }
    return result;
}

int refit_build_spatial_node_native(
    RefitSpatialIndexNative& index,
    std::size_t begin,
    std::size_t end
) {
    RefitSpatialNodeNative node;
    node.begin = begin;
    node.end = end;
    const RefitSpatialTriangleNative& first = index.triangles[index.triangle_order[begin]];
    node.minimum = first.minimum;
    node.maximum = first.maximum;
    Vec3 centroid_minimum = first.centroid;
    Vec3 centroid_maximum = first.centroid;
    for (std::size_t position = begin + 1; position < end; ++position) {
        const RefitSpatialTriangleNative& triangle = index.triangles[index.triangle_order[position]];
        for (std::size_t axis = 0; axis < 3; ++axis) {
            node.minimum[axis] = std::min(node.minimum[axis], triangle.minimum[axis]);
            node.maximum[axis] = std::max(node.maximum[axis], triangle.maximum[axis]);
            centroid_minimum[axis] = std::min(centroid_minimum[axis], triangle.centroid[axis]);
            centroid_maximum[axis] = std::max(centroid_maximum[axis], triangle.centroid[axis]);
        }
    }
    const int node_index = static_cast<int>(index.nodes.size());
    index.nodes.push_back(node);
    if (end - begin <= 8) return node_index;
    std::size_t split_axis = 0;
    for (std::size_t axis = 1; axis < 3; ++axis) {
        if (centroid_maximum[axis] - centroid_minimum[axis]
            > centroid_maximum[split_axis] - centroid_minimum[split_axis]) {
            split_axis = axis;
        }
    }
    std::stable_sort(
        index.triangle_order.begin() + static_cast<std::ptrdiff_t>(begin),
        index.triangle_order.begin() + static_cast<std::ptrdiff_t>(end),
        [&index, split_axis](std::size_t left, std::size_t right) {
            const auto& a = index.triangles[left];
            const auto& b = index.triangles[right];
            if (a.centroid[split_axis] != b.centroid[split_axis]) {
                return a.centroid[split_axis] < b.centroid[split_axis];
            }
            return a.source_order < b.source_order;
        }
    );
    const std::size_t middle = begin + (end - begin) / 2;
    index.nodes[static_cast<std::size_t>(node_index)].left = refit_build_spatial_node_native(index, begin, middle);
    index.nodes[static_cast<std::size_t>(node_index)].right = refit_build_spatial_node_native(index, middle, end);
    return node_index;
}

RefitSpatialIndexNative build_refit_spatial_index_native(
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::set<int>& drivers
) {
    RefitSpatialIndexNative index;
    for (const int driver_index : drivers) {
        const auto found = submeshes.find(driver_index);
        if (found == submeshes.end()) continue;
        for (const auto& face : found->second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= found->second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= found->second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= found->second.vertices.size()) continue;
            RefitSpatialTriangleNative triangle;
            triangle.driver_submesh_index = driver_index;
            triangle.driver_vertices = face;
            triangle.source_order = index.triangles.size();
            for (std::size_t corner = 0; corner < 3; ++corner) {
                triangle.corners[corner] = found->second.vertices[static_cast<std::size_t>(face[corner])];
            }
            triangle.minimum = triangle.maximum = triangle.corners[0];
            triangle.centroid = Vec3{0.0, 0.0, 0.0};
            for (const Vec3& corner : triangle.corners) {
                triangle.centroid = add_vec3(triangle.centroid, scale_vec3(corner, 1.0 / 3.0));
                for (std::size_t axis = 0; axis < 3; ++axis) {
                    triangle.minimum[axis] = std::min(triangle.minimum[axis], corner[axis]);
                    triangle.maximum[axis] = std::max(triangle.maximum[axis], corner[axis]);
                }
            }
            index.triangles.push_back(std::move(triangle));
        }
    }
    index.triangle_order.reserve(index.triangles.size());
    for (std::size_t position = 0; position < index.triangles.size(); ++position) {
        index.triangle_order.push_back(position);
    }
    if (!index.triangles.empty()) {
        index.nodes.reserve(index.triangles.size() * 2);
        index.root = refit_build_spatial_node_native(index, 0, index.triangles.size());
    }
    return index;
}

void query_refit_spatial_node_native(
    const RefitSpatialIndexNative& index,
    int node_index,
    const Vec3& point,
    ClosestTrianglePointNative& closest,
    std::size_t& closest_order,
    MeshRefitVertexBindingRuntime& binding,
    long long& candidate_tests
) {
    const RefitSpatialNodeNative& node = index.nodes[static_cast<std::size_t>(node_index)];
    if (refit_aabb_distance_squared_native(point, node.minimum, node.maximum) > closest.distance_squared) return;
    if (node.left < 0 || node.right < 0) {
        for (std::size_t position = node.begin; position < node.end; ++position) {
            const RefitSpatialTriangleNative& triangle = index.triangles[index.triangle_order[position]];
            ++candidate_tests;
            const ClosestTrianglePointNative candidate = closest_triangle_point_native(
                point, triangle.corners[0], triangle.corners[1], triangle.corners[2]
            );
            if (candidate.distance_squared < closest.distance_squared
                || (candidate.distance_squared == closest.distance_squared && triangle.source_order < closest_order)) {
                closest = candidate;
                closest_order = triangle.source_order;
                binding.driver_submesh_index = triangle.driver_submesh_index;
                binding.driver_vertices = triangle.driver_vertices;
                binding.barycentric = candidate.barycentric;
            }
        }
        return;
    }
    const auto& left = index.nodes[static_cast<std::size_t>(node.left)];
    const auto& right = index.nodes[static_cast<std::size_t>(node.right)];
    const double left_distance = refit_aabb_distance_squared_native(point, left.minimum, left.maximum);
    const double right_distance = refit_aabb_distance_squared_native(point, right.minimum, right.maximum);
    const int first = left_distance <= right_distance ? node.left : node.right;
    const int second = left_distance <= right_distance ? node.right : node.left;
    query_refit_spatial_node_native(index, first, point, closest, closest_order, binding, candidate_tests);
    query_refit_spatial_node_native(index, second, point, closest, closest_order, binding, candidate_tests);
}

MeshRefitVertexBindingRuntime closest_refit_binding_native(
    const Vec3& point,
    const RefitSpatialIndexNative& index,
    long long& candidate_tests
) {
    ClosestTrianglePointNative closest;
    std::size_t closest_order = std::numeric_limits<std::size_t>::max();
    MeshRefitVertexBindingRuntime binding;
    if (index.root >= 0) {
        query_refit_spatial_node_native(
            index, index.root, point, closest, closest_order, binding, candidate_tests
        );
    }
    if (binding.driver_submesh_index < 0 || !std::isfinite(closest.distance_squared)) {
        throw std::runtime_error("garment refit could not bind every vertex to a driver triangle");
    }
    binding.distance = std::sqrt(std::max(0.0, closest.distance_squared));
    return binding;
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
