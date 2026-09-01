bool mesh_interaction_snapshot_matches(
    const MeshInteractionAbiSession& runtime,
    const CdmwMeshInteractionGestureV1& request
) {
    const MeshInteractionSnapshot& snapshot = runtime.snapshot;
    return snapshot.ready
        && snapshot.mesh_revision == request.mesh_revision
        && snapshot.topology_generation == request.topology_generation
        && snapshot.camera_revision == request.camera_revision
        && snapshot.viewport_revision == request.viewport_revision
        && snapshot.xray == (request.xray != 0);
}

std::set<std::size_t> mesh_interaction_bucket_candidates(
    const std::unordered_map<int64_t, std::vector<std::size_t>>& buckets,
    const std::array<double, 4>& bounds,
    const std::vector<std::size_t>& large = {}
) {
    std::set<std::size_t> result(large.begin(), large.end());
    const int min_x = mesh_interaction_bucket_coordinate(bounds[0]);
    const int min_y = mesh_interaction_bucket_coordinate(bounds[1]);
    const int max_x = mesh_interaction_bucket_coordinate(bounds[2]);
    const int max_y = mesh_interaction_bucket_coordinate(bounds[3]);
    const int64_t width = static_cast<int64_t>(max_x) - min_x + 1;
    const int64_t height = static_cast<int64_t>(max_y) - min_y + 1;
    if (width <= 0 || height <= 0) return result;
    const uint64_t unsigned_width = static_cast<uint64_t>(width);
    const uint64_t unsigned_height = static_cast<uint64_t>(height);
    const bool cell_count_overflow = unsigned_width
        > std::numeric_limits<uint64_t>::max() / unsigned_height;
    const uint64_t cell_count = cell_count_overflow ? 0 : unsigned_width * unsigned_height;
    if (cell_count_overflow || cell_count > buckets.size()) {
        for (const auto& bucket : buckets) {
            result.insert(bucket.second.begin(), bucket.second.end());
        }
        return result;
    }
    for (int64_t y = min_y; y <= max_y; ++y) {
        for (int64_t x = min_x; x <= max_x; ++x) {
            const auto found = buckets.find(mesh_interaction_bucket_key(
                static_cast<int>(x), static_cast<int>(y)
            ));
            if (found != buckets.end()) result.insert(found->second.begin(), found->second.end());
        }
    }
    return result;
}

double mesh_interaction_edge_value(
    double ax, double ay, double bx, double by, double px, double py
) {
    return (px - ax) * (by - ay) - (py - ay) * (bx - ax);
}

bool mesh_interaction_point_in_triangle(
    double x,
    double y,
    const std::array<double, 9>& triangle,
    double* depth = nullptr
) {
    const double area = mesh_interaction_edge_value(
        triangle[0], triangle[1], triangle[3], triangle[4], triangle[6], triangle[7]
    );
    if (std::abs(area) <= 1e-12) return false;
    const double w0 = mesh_interaction_edge_value(
        triangle[3], triangle[4], triangle[6], triangle[7], x, y
    ) / area;
    const double w1 = mesh_interaction_edge_value(
        triangle[6], triangle[7], triangle[0], triangle[1], x, y
    ) / area;
    const double w2 = 1.0 - w0 - w1;
    if (w0 < -1e-9 || w1 < -1e-9 || w2 < -1e-9) return false;
    if (depth != nullptr) {
        *depth = w0 * triangle[2] + w1 * triangle[5] + w2 * triangle[8];
    }
    return true;
}

double mesh_interaction_front_depth(
    const MeshInteractionSnapshot& snapshot,
    double x,
    double y
) {
    double depth = std::numeric_limits<double>::infinity();
    if (snapshot.depth_bvh.empty()) return depth;
    std::vector<int> stack{0};
    while (!stack.empty()) {
        const int index = stack.back();
        stack.pop_back();
        const auto& node = snapshot.depth_bvh[static_cast<std::size_t>(index)];
        if (x < node.bounds[0] || y < node.bounds[1]
            || x > node.bounds[2] || y > node.bounds[3]) {
            continue;
        }
        if (node.left >= 0 || node.right >= 0) {
            if (node.left >= 0) stack.push_back(node.left);
            if (node.right >= 0) stack.push_back(node.right);
            continue;
        }
        for (std::size_t offset = node.first; offset < node.first + node.count; ++offset) {
            double candidate = 0.0;
            const auto& face = snapshot.faces[snapshot.depth_face_order[offset]];
            if (mesh_interaction_point_in_triangle(x, y, face.projected, &candidate)) {
                depth = std::min(depth, candidate);
            }
        }
    }
    return depth;
}

bool mesh_interaction_depth_visible(
    const MeshInteractionSnapshot& snapshot,
    double x,
    double y,
    double depth
) {
    if (snapshot.xray) return true;
    const double front = mesh_interaction_front_depth(snapshot, x, y);
    return !std::isfinite(front) || depth <= front + 1e-5;
}

bool mesh_interaction_point_in_polygon(
    double x,
    double y,
    const CdmwMeshInteractionGestureV1& request
) {
    bool inside = false;
    for (uint32_t left = 0, right = request.point_count - 1; left < request.point_count; right = left++) {
        const double ax = request.points_xy[static_cast<std::size_t>(left) * 2];
        const double ay = request.points_xy[static_cast<std::size_t>(left) * 2 + 1];
        const double bx = request.points_xy[static_cast<std::size_t>(right) * 2];
        const double by = request.points_xy[static_cast<std::size_t>(right) * 2 + 1];
        const bool crossing = ((ay > y) != (by > y))
            && (x < (bx - ax) * (y - ay) / ((by - ay) + 1e-30) + ax);
        if (crossing) inside = !inside;
    }
    return inside;
}

std::array<double, 4> mesh_interaction_shape_bounds(
    const CdmwMeshInteractionGestureV1& request
) {
    if (request.selection_shape == CDMW_MESH_SELECTION_BRUSH) {
        return {
            request.current_x - request.radius_pixels,
            request.current_y - request.radius_pixels,
            request.current_x + request.radius_pixels,
            request.current_y + request.radius_pixels,
        };
    }
    if (request.selection_shape == CDMW_MESH_SELECTION_RECTANGLE) {
        return mesh_interaction_bounds(
            request.start_x, request.start_y, request.current_x, request.current_y
        );
    }
    std::array<double, 4> result{
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
    };
    for (uint32_t index = 0; index < request.point_count; ++index) {
        const double x = request.points_xy[static_cast<std::size_t>(index) * 2];
        const double y = request.points_xy[static_cast<std::size_t>(index) * 2 + 1];
        result[0] = std::min(result[0], x);
        result[1] = std::min(result[1], y);
        result[2] = std::max(result[2], x);
        result[3] = std::max(result[3], y);
    }
    return result;
}

bool mesh_interaction_point_in_shape(
    double x,
    double y,
    const CdmwMeshInteractionGestureV1& request
) {
    if (request.selection_shape == CDMW_MESH_SELECTION_BRUSH) {
        return std::hypot(x - request.current_x, y - request.current_y) <= request.radius_pixels;
    }
    if (request.selection_shape == CDMW_MESH_SELECTION_RECTANGLE) {
        const auto bounds = mesh_interaction_shape_bounds(request);
        return x >= bounds[0] && y >= bounds[1] && x <= bounds[2] && y <= bounds[3];
    }
    return mesh_interaction_point_in_polygon(x, y, request);
}

int mesh_interaction_orientation(
    double ax, double ay, double bx, double by, double cx, double cy
) {
    const double value = mesh_interaction_edge_value(ax, ay, bx, by, cx, cy);
    return value > 1e-9 ? 1 : value < -1e-9 ? -1 : 0;
}

bool mesh_interaction_point_on_segment(
    double ax, double ay, double bx, double by, double px, double py
) {
    return mesh_interaction_orientation(ax, ay, bx, by, px, py) == 0
        && px >= std::min(ax, bx) - 1e-9
        && px <= std::max(ax, bx) + 1e-9
        && py >= std::min(ay, by) - 1e-9
        && py <= std::max(ay, by) + 1e-9;
}

bool mesh_interaction_segments_intersect(
    double ax, double ay, double bx, double by,
    double cx, double cy, double dx, double dy
) {
    const int a = mesh_interaction_orientation(ax, ay, bx, by, cx, cy);
    const int b = mesh_interaction_orientation(ax, ay, bx, by, dx, dy);
    const int c = mesh_interaction_orientation(cx, cy, dx, dy, ax, ay);
    const int d = mesh_interaction_orientation(cx, cy, dx, dy, bx, by);
    if (a != b && c != d) return true;
    return (a == 0 && mesh_interaction_point_on_segment(ax, ay, bx, by, cx, cy))
        || (b == 0 && mesh_interaction_point_on_segment(ax, ay, bx, by, dx, dy))
        || (c == 0 && mesh_interaction_point_on_segment(cx, cy, dx, dy, ax, ay))
        || (d == 0 && mesh_interaction_point_on_segment(cx, cy, dx, dy, bx, by));
}

bool mesh_interaction_segment_hits_shape(
    double ax,
    double ay,
    double bx,
    double by,
    const CdmwMeshInteractionGestureV1& request
) {
    if (mesh_interaction_point_in_shape(ax, ay, request)
        || mesh_interaction_point_in_shape(bx, by, request)) {
        return true;
    }
    if (request.selection_shape == CDMW_MESH_SELECTION_BRUSH) {
        return mesh_editor_screen_segment_distance(
            request.current_x, request.current_y, ax, ay, bx, by
        ) <= request.radius_pixels;
    }
    if (request.selection_shape == CDMW_MESH_SELECTION_RECTANGLE) {
        const auto bounds = mesh_interaction_shape_bounds(request);
        const std::array<std::array<double, 4>, 4> edges{{
            {bounds[0], bounds[1], bounds[2], bounds[1]},
            {bounds[2], bounds[1], bounds[2], bounds[3]},
            {bounds[2], bounds[3], bounds[0], bounds[3]},
            {bounds[0], bounds[3], bounds[0], bounds[1]},
        }};
        return std::any_of(edges.begin(), edges.end(), [&](const auto& edge) {
            return mesh_interaction_segments_intersect(
                ax, ay, bx, by, edge[0], edge[1], edge[2], edge[3]
            );
        });
    }
    for (uint32_t left = 0, right = request.point_count - 1; left < request.point_count; right = left++) {
        if (mesh_interaction_segments_intersect(
                ax, ay, bx, by,
                request.points_xy[static_cast<std::size_t>(right) * 2],
                request.points_xy[static_cast<std::size_t>(right) * 2 + 1],
                request.points_xy[static_cast<std::size_t>(left) * 2],
                request.points_xy[static_cast<std::size_t>(left) * 2 + 1])) {
            return true;
        }
    }
    return false;
}

const MeshInteractionProjectedVertex* mesh_interaction_projected_vertex(
    const MeshInteractionSnapshot& snapshot,
    int submesh_index,
    int vertex_index
) {
    const auto lookup = snapshot.vertex_lookup.find(submesh_index);
    if (lookup == snapshot.vertex_lookup.end()
        || vertex_index < 0
        || static_cast<std::size_t>(vertex_index) >= lookup->second.size()) {
        return nullptr;
    }
    const std::size_t slot = lookup->second[static_cast<std::size_t>(vertex_index)];
    return slot < snapshot.vertices.size() ? &snapshot.vertices[slot] : nullptr;
}

MeshEditorSelection mesh_interaction_typed_selection_candidates(
    const MeshInteractionSnapshot& snapshot,
    const CdmwMeshInteractionGestureV1& request
) {
    MeshEditorSelection result;
    const auto bounds = mesh_interaction_shape_bounds(request);
    if (request.selection_target == CDMW_MESH_SELECTION_VERTEX) {
        for (const std::size_t slot : mesh_interaction_bucket_candidates(
                snapshot.vertex_buckets, bounds)) {
            const auto& vertex = snapshot.vertices[slot];
            if (mesh_interaction_point_in_shape(vertex.x, vertex.y, request)
                && mesh_interaction_depth_visible(snapshot, vertex.x, vertex.y, vertex.depth)) {
                result.vertices[vertex.submesh_index].insert(vertex.vertex_index);
            }
        }
    } else if (request.selection_target == CDMW_MESH_SELECTION_EDGE) {
        for (const std::size_t slot : mesh_interaction_bucket_candidates(
                snapshot.edge_buckets, bounds, snapshot.large_edges)) {
            const auto& edge = snapshot.edges[slot];
            const auto* a = mesh_interaction_projected_vertex(
                snapshot, edge.submesh_index, edge.vertex_a
            );
            const auto* b = mesh_interaction_projected_vertex(
                snapshot, edge.submesh_index, edge.vertex_b
            );
            if (a == nullptr || b == nullptr
                || !mesh_interaction_segment_hits_shape(a->x, a->y, b->x, b->y, request)) {
                continue;
            }
            const double x = (a->x + b->x) * 0.5;
            const double y = (a->y + b->y) * 0.5;
            const double depth = (a->depth + b->depth) * 0.5;
            if (mesh_interaction_depth_visible(snapshot, x, y, depth)) {
                result.edges[edge.submesh_index].insert({edge.vertex_a, edge.vertex_b});
            }
        }
    } else {
        for (const std::size_t slot : mesh_interaction_bucket_candidates(
                snapshot.face_buckets, bounds, snapshot.large_faces)) {
            const auto& face = snapshot.faces[slot];
            bool hit = mesh_interaction_point_in_shape(face.projected[0], face.projected[1], request)
                || mesh_interaction_point_in_shape(face.projected[3], face.projected[4], request)
                || mesh_interaction_point_in_shape(face.projected[6], face.projected[7], request);
            if (!hit && request.selection_shape == CDMW_MESH_SELECTION_BRUSH) {
                hit = mesh_editor_screen_triangle_distance(
                    request.current_x,
                    request.current_y,
                    face.projected[0], face.projected[1],
                    face.projected[3], face.projected[4],
                    face.projected[6], face.projected[7]
                ) <= request.radius_pixels;
            }
            if (!hit) {
                hit = mesh_interaction_segment_hits_shape(
                    face.projected[0], face.projected[1],
                    face.projected[3], face.projected[4], request
                ) || mesh_interaction_segment_hits_shape(
                    face.projected[3], face.projected[4],
                    face.projected[6], face.projected[7], request
                ) || mesh_interaction_segment_hits_shape(
                    face.projected[6], face.projected[7],
                    face.projected[0], face.projected[1], request
                );
            }
            if (!hit && request.selection_shape == CDMW_MESH_SELECTION_RECTANGLE) {
                const auto rectangle = mesh_interaction_shape_bounds(request);
                const std::array<std::array<double, 2>, 4> corners{{
                    {rectangle[0], rectangle[1]},
                    {rectangle[2], rectangle[1]},
                    {rectangle[2], rectangle[3]},
                    {rectangle[0], rectangle[3]},
                }};
                hit = std::any_of(corners.begin(), corners.end(), [&](const auto& point) {
                    return mesh_interaction_point_in_triangle(
                        point[0], point[1], face.projected
                    );
                });
            } else if (!hit && request.selection_shape == CDMW_MESH_SELECTION_LASSO) {
                for (uint32_t index = 0; index < request.point_count && !hit; ++index) {
                    hit = mesh_interaction_point_in_triangle(
                        request.points_xy[static_cast<std::size_t>(index) * 2],
                        request.points_xy[static_cast<std::size_t>(index) * 2 + 1],
                        face.projected
                    );
                }
            }
            const double x = (face.projected[0] + face.projected[3] + face.projected[6]) / 3.0;
            const double y = (face.projected[1] + face.projected[4] + face.projected[7]) / 3.0;
            const double depth = (face.projected[2] + face.projected[5] + face.projected[8]) / 3.0;
            if (hit && mesh_interaction_depth_visible(snapshot, x, y, depth)) {
                result.faces[face.submesh_index].insert(face.face_index);
            }
        }
    }
    return result;
}

std::map<int, std::map<int, double>> mesh_interaction_brush_weights(
    const MeshInteractionSnapshot& snapshot,
    double x,
    double y,
    double radius,
    const std::map<int, std::map<int, double>>& selection_scope
) {
    std::map<int, std::map<int, double>> result;
    const std::array<double, 4> bounds{x - radius, y - radius, x + radius, y + radius};
    for (const std::size_t slot : mesh_interaction_bucket_candidates(
            snapshot.vertex_buckets, bounds)) {
        const auto& vertex = snapshot.vertices[slot];
        const double distance = std::hypot(vertex.x - x, vertex.y - y);
        if (distance > radius
            || !mesh_interaction_depth_visible(snapshot, vertex.x, vertex.y, vertex.depth)) {
            continue;
        }
        if (!selection_scope.empty()) {
            const auto selected_group = selection_scope.find(vertex.submesh_index);
            if (selected_group == selection_scope.end()
                || selected_group->second.find(vertex.vertex_index) == selected_group->second.end()) {
                continue;
            }
        }
        const double linear = std::max(0.0, 1.0 - distance / std::max(radius, 1e-8));
        result[vertex.submesh_index][vertex.vertex_index] = linear * linear * (3.0 - 2.0 * linear);
    }
    return result;
}

std::map<int, std::map<int, double>> mesh_interaction_selected_weights(
    const MeshEditorSession& editor,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    std::map<int, std::map<int, double>> result;
    for (const auto& item : editor.selection.vertices) {
        for (const int index : item.second) result[item.first][index] = 1.0;
    }
    for (const auto& item : editor.selection.edges) {
        for (const auto& edge : item.second) {
            result[item.first][edge[0]] = 1.0;
            result[item.first][edge[1]] = 1.0;
        }
    }
    for (const auto& item : editor.selection.faces) {
        const auto submesh = submeshes.find(item.first);
        if (submesh == submeshes.end()) continue;
        for (const int face_index : item.second) {
            if (face_index < 0
                || static_cast<std::size_t>(face_index) >= submesh->second.faces.size()) continue;
            for (const int vertex : submesh->second.faces[static_cast<std::size_t>(face_index)]) {
                result[item.first][vertex] = 1.0;
            }
        }
    }
    for (const int source : editor.selection.source_indices) {
        const auto submesh = submeshes.find(source);
        if (submesh == submeshes.end()) continue;
        for (std::size_t index = 0; index < submesh->second.vertices.size(); ++index) {
            result[source][static_cast<int>(index)] = 1.0;
        }
    }
    return result;
}

void mesh_interaction_record_before(
    MeshInteractionAbiSession& runtime,
    int submesh_index,
    int vertex_index,
    const Vec3& value
) {
    runtime.gesture_before_positions[submesh_index].try_emplace(vertex_index, value);
}

void mesh_interaction_recompute_normals(MeshSessionSubmesh& submesh) {
    submesh.normals = compute_smooth_normals(submesh.vertices, submesh.faces);
}

void mesh_interaction_refresh_projected_vertices(
    MeshInteractionAbiSession& runtime,
    const std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::set<int>>& changed
) {
    for (const auto& item : changed) {
        const auto matrix = runtime.submesh_world_view_projections.find(item.first);
        const auto submesh = submeshes.find(item.first);
        const auto lookup = runtime.snapshot.vertex_lookup.find(item.first);
        if (matrix == runtime.submesh_world_view_projections.end()
            || submesh == submeshes.end()
            || lookup == runtime.snapshot.vertex_lookup.end()) continue;
        for (const int vertex_index : item.second) {
            if (vertex_index < 0
                || static_cast<std::size_t>(vertex_index) >= lookup->second.size()
                || static_cast<std::size_t>(vertex_index) >= submesh->second.vertices.size()) continue;
            const std::size_t slot = lookup->second[static_cast<std::size_t>(vertex_index)];
            if (slot >= runtime.snapshot.vertices.size()) continue;
            auto& projected = runtime.snapshot.vertices[slot];
            const int old_x = mesh_interaction_bucket_coordinate(projected.x);
            const int old_y = mesh_interaction_bucket_coordinate(projected.y);
            auto old_bucket = runtime.snapshot.vertex_buckets.find(
                mesh_interaction_bucket_key(old_x, old_y)
            );
            if (old_bucket != runtime.snapshot.vertex_buckets.end()) {
                auto& values = old_bucket->second;
                values.erase(std::remove(values.begin(), values.end(), slot), values.end());
            }
            if (project_vertex_with_matrix_depth(
                    matrix->second,
                    submesh->second.vertices[static_cast<std::size_t>(vertex_index)],
                    0.0,
                    0.0,
                    runtime.viewport_width,
                    runtime.viewport_height,
                    projected.x,
                    projected.y,
                    projected.depth)) {
                const int cell_x = mesh_interaction_bucket_coordinate(projected.x);
                const int cell_y = mesh_interaction_bucket_coordinate(projected.y);
                runtime.snapshot.vertex_buckets[mesh_interaction_bucket_key(cell_x, cell_y)].push_back(slot);
            }
        }
    }
}

void mesh_interaction_apply_weighted_delta(
    MeshInteractionAbiSession& runtime,
    std::map<int, MeshSessionSubmesh>& submeshes,
    const std::map<int, std::map<int, double>>& weights,
    const CdmwMeshInteractionGestureV1& request,
    double amount_scale
) {
    const bool tracks_pointer_delta = request.tool == CDMW_MESH_TOOL_MOVE
        || request.tool == CDMW_MESH_TOOL_GRAB;
    const double strength = tracks_pointer_delta
        ? 1.0
        : std::clamp(request.strength * std::max(0.0, request.pressure), 0.0, 1.0);
    const Vec3 delta{request.delta_x * amount_scale, request.delta_y * amount_scale, request.delta_z * amount_scale};
    for (const auto& group : weights) {
        auto submesh = submeshes.find(group.first);
        if (submesh == submeshes.end()) continue;
        const std::vector<Vec3> original = submesh->second.vertices;
        std::vector<Vec3> smooth_positions = original;
        if (request.tool == CDMW_MESH_TOOL_SMOOTH) {
            const auto adjacency = runtime.snapshot.adjacency.find(group.first);
            if (adjacency != runtime.snapshot.adjacency.end()) {
                for (const auto& weighted : group.second) {
                    const int index = weighted.first;
                    if (index < 0 || static_cast<std::size_t>(index) >= original.size()
                        || static_cast<std::size_t>(index) >= adjacency->second.size()
                        || adjacency->second[static_cast<std::size_t>(index)].empty()) continue;
                    Vec3 average{0.0, 0.0, 0.0};
                    for (const int neighbor : adjacency->second[static_cast<std::size_t>(index)]) {
                        average = add_vec3(average, original[static_cast<std::size_t>(neighbor)]);
                    }
                    average = scale_vec3(
                        average,
                        1.0 / adjacency->second[static_cast<std::size_t>(index)].size()
                    );
                    smooth_positions[static_cast<std::size_t>(index)] = add_vec3(
                        original[static_cast<std::size_t>(index)],
                        scale_vec3(
                            sub_vec3(average, original[static_cast<std::size_t>(index)]),
                            strength * weighted.second * 0.35 * amount_scale
                        )
                    );
                }
            }
        }
        Vec3 center{0.0, 0.0, 0.0};
        double weight_sum = 0.0;
        double projected_depth = 0.0;
        double projected_weight_sum = 0.0;
        for (const auto& weighted : group.second) {
            if (weighted.first < 0 || static_cast<std::size_t>(weighted.first) >= original.size()) continue;
            center = add_vec3(
                center,
                scale_vec3(original[static_cast<std::size_t>(weighted.first)], weighted.second)
            );
            weight_sum += weighted.second;
            const auto* projected = mesh_interaction_projected_vertex(
                runtime.snapshot, group.first, weighted.first
            );
            if (projected != nullptr) {
                projected_depth += projected->depth * weighted.second;
                projected_weight_sum += weighted.second;
            }
        }
        if (weight_sum > 0.0) center = scale_vec3(center, 1.0 / weight_sum);
        double world_units_per_pixel = 0.0;
        if (request.tool == CDMW_MESH_TOOL_INFLATE && projected_weight_sum > 0.0) {
            const auto matrix = runtime.submesh_world_view_projections.find(group.first);
            std::array<double, 16> inverse{};
            Vec3 pointer_center{};
            Vec3 pointer_one_pixel_down{};
            if (matrix != runtime.submesh_world_view_projections.end()
                && matrix4x4_inverse(matrix->second, inverse)
                && unproject_screen_point_with_matrix_inverse(
                    inverse,
                    request.current_x,
                    request.current_y,
                    projected_depth / projected_weight_sum,
                    0.0,
                    0.0,
                    runtime.viewport_width,
                    runtime.viewport_height,
                    pointer_center)
                && unproject_screen_point_with_matrix_inverse(
                    inverse,
                    request.current_x,
                    request.current_y + 1.0,
                    projected_depth / projected_weight_sum,
                    0.0,
                    0.0,
                    runtime.viewport_width,
                    runtime.viewport_height,
                    pointer_one_pixel_down)) {
                world_units_per_pixel = length_vec3(
                    sub_vec3(pointer_one_pixel_down, pointer_center)
                );
            }
            if (!(world_units_per_pixel > 0.0) || !std::isfinite(world_units_per_pixel)) {
                throw std::runtime_error("inflate brush could not resolve world units per pixel");
            }
        }
        if (request.tool == CDMW_MESH_TOOL_PINCH && projected_weight_sum > 0.0) {
            const auto matrix = runtime.submesh_world_view_projections.find(group.first);
            std::array<double, 16> inverse{};
            Vec3 pointer_center{};
            if (matrix != runtime.submesh_world_view_projections.end()
                && matrix4x4_inverse(matrix->second, inverse)
                && unproject_screen_point_with_matrix_inverse(
                    inverse,
                    request.current_x,
                    request.current_y,
                    projected_depth / projected_weight_sum,
                    0.0,
                    0.0,
                    runtime.viewport_width,
                    runtime.viewport_height,
                    pointer_center)) {
                center = pointer_center;
            }
        }
        if (request.tool == CDMW_MESH_TOOL_INFLATE
            && submesh->second.normals.size() != submesh->second.vertices.size()) {
            mesh_interaction_recompute_normals(submesh->second);
        }
        for (const auto& weighted : group.second) {
            const int index = weighted.first;
            if (index < 0 || static_cast<std::size_t>(index) >= submesh->second.vertices.size()) continue;
            Vec3& vertex = submesh->second.vertices[static_cast<std::size_t>(index)];
            const Vec3 before = vertex;
            mesh_interaction_record_before(runtime, group.first, index, before);
            if (request.tool == CDMW_MESH_TOOL_MOVE || request.tool == CDMW_MESH_TOOL_GRAB) {
                vertex = add_vec3(vertex, scale_vec3(delta, weighted.second * strength));
            } else if (request.tool == CDMW_MESH_TOOL_SMOOTH) {
                vertex = smooth_positions[static_cast<std::size_t>(index)];
            } else if (request.tool == CDMW_MESH_TOOL_INFLATE) {
                const Vec3 normal = normalized_vec3(
                    submesh->second.normals[static_cast<std::size_t>(index)],
                    {0.0, 1.0, 0.0}
                );
                vertex = add_vec3(
                    vertex,
                    scale_vec3(
                        normal,
                        world_units_per_pixel * 8.0 * strength * amount_scale * weighted.second
                    )
                );
            } else if (request.tool == CDMW_MESH_TOOL_PINCH) {
                vertex = add_vec3(
                    vertex,
                    scale_vec3(
                        sub_vec3(center, vertex),
                        std::clamp(strength * 0.12 * amount_scale * weighted.second, 0.0, 1.0)
                    )
                );
            }
            if (!same_vec3(before, vertex)) {
                runtime.last_dirty_vertices[group.first].insert(index);
                runtime.gesture_changed_vertices[group.first].insert(index);
            }
        }
    }
    mesh_interaction_refresh_projected_vertices(runtime, submeshes, runtime.last_dirty_vertices);
}

void mesh_interaction_apply_typed_deformation(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const CdmwMeshInteractionGestureV1& request,
    const std::string& phase
) {
    auto* submeshes_pointer = mesh_interaction_abi_find_submeshes(runtime);
    if (submeshes_pointer == nullptr) throw std::runtime_error("resident mesh session is missing");
    auto& submeshes = *submeshes_pointer;
    runtime.last_dirty_vertices.clear();
    if (phase == "begin") {
        runtime.previous_screen_x = request.current_x;
        runtime.previous_screen_y = request.current_y;
        const auto selected_weights = mesh_interaction_selected_weights(editor, submeshes);
        if (request.tool == CDMW_MESH_TOOL_MOVE) {
            runtime.gesture_weights = selected_weights;
            if (runtime.gesture_weights.empty()) {
                throw std::invalid_argument("Move requires a committed mesh selection");
            }
            return;
        }
        if (request.tool == CDMW_MESH_TOOL_GRAB) {
            runtime.gesture_weights = mesh_interaction_brush_weights(
                runtime.snapshot,
                request.current_x,
                request.current_y,
                request.radius_pixels,
                selected_weights
            );
            if (runtime.gesture_weights.empty()) {
                throw std::invalid_argument("Grab requires mesh vertices under the brush");
            }
            return;
        }
        runtime.gesture_weights = selected_weights;
        const auto dab_weights = mesh_interaction_brush_weights(
            runtime.snapshot,
            request.current_x,
            request.current_y,
            request.radius_pixels,
            runtime.gesture_weights
        );
        if (dab_weights.empty()) {
            throw std::invalid_argument("Sculpt requires mesh vertices under the brush");
        }
        mesh_interaction_apply_weighted_delta(runtime, submeshes, dab_weights, request, 1.0);
        return;
    }
    if (phase == "end") {
        runtime.last_dirty_vertices = runtime.gesture_changed_vertices;
        for (const auto& group : runtime.gesture_changed_vertices) {
            auto submesh = submeshes.find(group.first);
            if (submesh != submeshes.end() && !group.second.empty()) {
                mesh_interaction_recompute_normals(submesh->second);
            }
        }
        return;
    }
    if (request.tool == CDMW_MESH_TOOL_MOVE || request.tool == CDMW_MESH_TOOL_GRAB) {
        mesh_interaction_apply_weighted_delta(runtime, submeshes, runtime.gesture_weights, request, 1.0);
    } else {
        const double distance = std::hypot(
            request.current_x - runtime.previous_screen_x,
            request.current_y - runtime.previous_screen_y
        );
        const int samples = std::max(
            1,
            static_cast<int>(std::ceil(distance / std::max(2.0, request.radius_pixels * 0.35)))
        );
        for (int sample = 1; sample <= samples; ++sample) {
            const double amount = static_cast<double>(sample) / samples;
            const double x = runtime.previous_screen_x
                + (request.current_x - runtime.previous_screen_x) * amount;
            const double y = runtime.previous_screen_y
                + (request.current_y - runtime.previous_screen_y) * amount;
            const auto weights = mesh_interaction_brush_weights(
                runtime.snapshot,
                x,
                y,
                request.radius_pixels,
                runtime.gesture_weights
            );
            mesh_interaction_apply_weighted_delta(
                runtime, submeshes, weights, request, 1.0 / samples
            );
        }
    }
    runtime.previous_screen_x = request.current_x;
    runtime.previous_screen_y = request.current_y;
}

void mesh_interaction_append_typed_dirty(
    const MeshInteractionAbiSession& runtime,
    std::map<int, MeshInteractionAbiDirtySet>& dirty
) {
    const auto* submeshes_pointer = mesh_interaction_abi_find_submeshes(runtime);
    if (submeshes_pointer == nullptr) return;
    const auto& submeshes = *submeshes_pointer;
    for (const auto& item : runtime.last_dirty_vertices) {
        MeshInteractionAbiDirtySet& target = dirty[item.first];
        target.indices.insert(item.second.begin(), item.second.end());
        const auto submesh = submeshes.find(item.first);
        target.vertex_count = submesh == submeshes.end()
            ? 0u : static_cast<uint32_t>(submesh->second.vertices.size());
    }
}

void mesh_interaction_commit_typed_history(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor
) {
    MeshEditorHistoryEntry entry;
    entry.operation = runtime.active_tool == CDMW_MESH_TOOL_SELECT
        ? "select"
        : runtime.active_tool == CDMW_MESH_TOOL_MOVE ? "transform" : "brush";
    entry.stroke_id = std::to_string(runtime.active_gesture_id);
    if (runtime.active_tool == CDMW_MESH_TOOL_SELECT) {
        if (runtime.baseline_selection.vertices == editor.selection.vertices
            && runtime.baseline_selection.edges == editor.selection.edges
            && runtime.baseline_selection.faces == editor.selection.faces
            && runtime.baseline_selection.source_indices == editor.selection.source_indices) {
            return;
        }
        entry.selection_snapshot = true;
        entry.selection_before = runtime.baseline_selection;
    } else {
        const auto* submeshes_pointer = mesh_interaction_abi_find_submeshes(runtime);
        if (submeshes_pointer == nullptr) throw std::runtime_error("resident mesh session is missing");
        const auto& submeshes = *submeshes_pointer;
        for (const auto& group : runtime.gesture_before_positions) {
            const auto submesh = submeshes.find(group.first);
            if (submesh == submeshes.end()) continue;
            MeshEditorSubmeshDelta delta;
            delta.vertices.before_size = submesh->second.vertices.size();
            delta.vertices.after_size = submesh->second.vertices.size();
            for (const auto& vertex : group.second) {
                if (vertex.first < 0
                    || static_cast<std::size_t>(vertex.first) >= submesh->second.vertices.size()
                    || same_vec3(vertex.second, submesh->second.vertices[static_cast<std::size_t>(vertex.first)])) {
                    continue;
                }
                delta.vertices.indices.push_back(vertex.first);
                delta.vertices.before_values.push_back(vertex.second);
                delta.vertices.after_values.push_back(
                    submesh->second.vertices[static_cast<std::size_t>(vertex.first)]
                );
            }
            if (!delta.vertices.indices.empty()) entry.deltas[group.first] = std::move(delta);
        }
        if (entry.deltas.empty()) return;
    }
    mesh_editor_push_history(editor.undo_stack, std::move(entry));
    editor.redo_stack.clear();
    mesh_editor_trim_session_history(editor);
    ++editor.edit_revision;
}

void mesh_interaction_cancel_typed_gesture(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor
) {
    auto* submeshes_pointer = mesh_interaction_abi_find_submeshes(runtime);
    if (submeshes_pointer == nullptr) throw std::runtime_error("resident mesh session is missing");
    auto& submeshes = *submeshes_pointer;
    runtime.last_dirty_vertices.clear();
    for (const auto& group : runtime.gesture_before_positions) {
        auto submesh = submeshes.find(group.first);
        if (submesh == submeshes.end()) continue;
        for (const auto& vertex : group.second) {
            if (vertex.first < 0
                || static_cast<std::size_t>(vertex.first) >= submesh->second.vertices.size()) continue;
            submesh->second.vertices[static_cast<std::size_t>(vertex.first)] = vertex.second;
            runtime.last_dirty_vertices[group.first].insert(vertex.first);
        }
        mesh_interaction_recompute_normals(submesh->second);
    }
    editor.selection = runtime.baseline_selection;
    ++editor.selection_revision;
}
