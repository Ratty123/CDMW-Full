bool mesh_editor_screen_brush_submesh_allowed(const JsonValue& item, const JsonValue& brush) {
    const std::vector<int> indices = int_vector_from_json(brush.get("source_submesh_indices"));
    if (indices.empty()) {
        return true;
    }
    const int submesh_index = int_or(item.get("index"), -1);
    return std::find(indices.begin(), indices.end(), submesh_index) != indices.end();
}

struct MeshEditorScreenBrushProjection {
    double viewport_width = 1.0;
    double viewport_height = 1.0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    std::array<double, 16> camera_world{};
    std::array<double, 16> world_view_projection{};
    std::map<int, std::array<double, 16>> source_world_view_projections;
    std::set<int> source_projection_overrides;
    bool has_camera_world = false;
    bool has_world_view_projection = false;
    bool projection_payload_unresolved = false;
};

struct MeshEditorScreenRay {
    Vec3 origin{0.0, 0.0, 0.0};
    Vec3 direction{0.0, 0.0, 0.0};
};

MeshEditorScreenBrushProjection mesh_editor_screen_brush_projection(const JsonValue& brush) {
    MeshEditorScreenBrushProjection projection;
    projection.viewport_width = std::max(number_or(brush.get("viewport_width"), number_or(brush.get("width"), 0.0)), 1.0);
    projection.viewport_height = std::max(number_or(brush.get("viewport_height"), number_or(brush.get("height"), 0.0)), 1.0);
    projection.viewport_x = number_or(brush.get("viewport_x"), number_or(brush.get("top_left_x"), 0.0));
    projection.viewport_y = number_or(brush.get("viewport_y"), number_or(brush.get("top_left_y"), 0.0));
    projection.has_camera_world = matrix4x4_from_json(brush.get("camera_world"), projection.camera_world);
    projection.has_world_view_projection = matrix4x4_from_json(brush.get("world_view_projection"), projection.world_view_projection);
    projection.projection_payload_unresolved = brush.get("world_view_projection") != nullptr && !projection.has_world_view_projection;
    for (const char* key : {"source_submesh_world_view_projections", "source_world_view_projections"}) {
        const JsonValue* overrides = brush.get(key);
        if (overrides == nullptr) {
            continue;
        }
        if (overrides->type != JsonValue::Type::Array) {
            projection.projection_payload_unresolved = true;
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int source_submesh_index = mesh_editor_source_projection_override_index(item);
            std::array<double, 16> source_world_view_projection{};
            if (source_submesh_index >= 0) {
                projection.source_projection_overrides.insert(source_submesh_index);
            }
            if (source_submesh_index >= 0
                && matrix4x4_from_json(item.get("world_view_projection"), source_world_view_projection)) {
                projection.source_world_view_projections[source_submesh_index] = source_world_view_projection;
            }
        }
    }
    for (const char* key : {"source_submesh_world_transforms", "source_world_transforms"}) {
        const JsonValue* overrides = brush.get(key);
        if (overrides == nullptr) {
            continue;
        }
        if (overrides->type != JsonValue::Type::Array) {
            projection.projection_payload_unresolved = true;
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int source_submesh_index = mesh_editor_source_projection_override_index(item);
            std::array<double, 16> source_world_transform{};
            if (source_submesh_index >= 0) {
                projection.source_projection_overrides.insert(source_submesh_index);
            }
            if (source_submesh_index >= 0
                && projection.has_world_view_projection
                && projection.source_world_view_projections.find(source_submesh_index) == projection.source_world_view_projections.end()
                && matrix4x4_from_transform_json(item, source_world_transform)) {
                projection.source_world_view_projections[source_submesh_index] =
                    matrix4x4_multiply(source_world_transform, projection.world_view_projection);
            }
        }
    }
    if (!projection.has_world_view_projection && !projection.source_projection_overrides.empty()) {
        projection.projection_payload_unresolved = true;
    }
    return projection;
}

MeshEditorScreenBrushProjection mesh_editor_projection_for_submesh(
    const MeshEditorScreenBrushProjection& projection,
    int source_submesh_index
) {
    const auto found = projection.source_world_view_projections.find(source_submesh_index);
    if (found == projection.source_world_view_projections.end()) {
        if (projection.source_projection_overrides.find(source_submesh_index) != projection.source_projection_overrides.end()) {
            MeshEditorScreenBrushProjection scoped = projection;
            scoped.has_camera_world = false;
            scoped.has_world_view_projection = false;
            scoped.projection_payload_unresolved = true;
            return scoped;
        }
        return projection;
    }
    MeshEditorScreenBrushProjection scoped = projection;
    scoped.world_view_projection = found->second;
    scoped.has_world_view_projection = true;
    scoped.projection_payload_unresolved = false;
    return scoped;
}

bool mesh_editor_screen_ray_from_projection(
    const JsonValue& brush,
    const MeshEditorScreenBrushProjection& projection,
    MeshEditorScreenRay& ray
) {
    if (projection.projection_payload_unresolved || !projection.has_world_view_projection) {
        return false;
    }
    const double screen_x = number_or(brush.get("x"), number_or(brush.get("cursor_x"), number_or(brush.get("screen_x"), std::numeric_limits<double>::quiet_NaN())));
    const double screen_y = number_or(brush.get("y"), number_or(brush.get("cursor_y"), number_or(brush.get("screen_y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(screen_x) || !std::isfinite(screen_y)) {
        return false;
    }
    std::array<double, 16> inverse_matrix{};
    if (!matrix4x4_inverse(projection.world_view_projection, inverse_matrix)) {
        return false;
    }
    Vec3 near_point{};
    Vec3 far_point{};
    if (!unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            screen_x,
            screen_y,
            0.0,
            projection.viewport_x,
            projection.viewport_y,
            projection.viewport_width,
            projection.viewport_height,
            near_point)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            screen_x,
            screen_y,
            1.0,
            projection.viewport_x,
            projection.viewport_y,
            projection.viewport_width,
            projection.viewport_height,
            far_point)) {
        return false;
    }
    const Vec3 direction = normalized_vec3(sub_vec3(far_point, near_point), {0.0, 0.0, 0.0});
    if (length_vec3(direction) <= 0.5) {
        return false;
    }
    ray.origin = near_point;
    ray.direction = direction;
    return true;
}

bool mesh_editor_project_screen_brush_vertex_with_matrix(
    const std::array<double, 16>& matrix,
    const Vec3& vertex,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    double& screen_x,
    double& screen_y
) {
    // Matches DirectX row-vector XMFLOAT4X4 layout from XMStoreFloat4x4.
    return project_vertex_with_matrix(matrix, vertex, viewport_x, viewport_y, viewport_width, viewport_height, screen_x, screen_y);
}

bool mesh_editor_project_screen_brush_vertex_with_projection(
    const JsonValue& brush,
    const MeshEditorScreenBrushProjection& projection,
    const Vec3& vertex,
    double& screen_x,
    double& screen_y,
    double* depth_z = nullptr
) {
    if (projection.projection_payload_unresolved) {
        return false;
    }
    if (projection.has_world_view_projection) {
        double projected_depth = 0.0;
        if (!project_vertex_with_matrix_depth(
            projection.world_view_projection,
            vertex,
            projection.viewport_x,
            projection.viewport_y,
            projection.viewport_width,
            projection.viewport_height,
            screen_x,
            screen_y,
            projected_depth
        )) {
            return false;
        }
        if (depth_z != nullptr) {
            *depth_z = projected_depth;
        }
        return true;
    }
    if (projection.projection_payload_unresolved) {
        return false;
    }
    const double distance = std::max(number_or(brush.get("distance"), 0.0), 0.1);
    const double fov = std::max(number_or(brush.get("vertical_fov_degrees"), 45.0), 1e-6);
    Vec3 world{};
    if (projection.has_camera_world) {
        const Vec3 right{projection.camera_world[0], projection.camera_world[1], projection.camera_world[2]};
        const Vec3 up{projection.camera_world[4], projection.camera_world[5], projection.camera_world[6]};
        const Vec3 forward{projection.camera_world[8], projection.camera_world[9], projection.camera_world[10]};
        const Vec3 origin{projection.camera_world[12], projection.camera_world[13], projection.camera_world[14]};
        world = {
            right[0] * vertex[0] + up[0] * vertex[1] + forward[0] * vertex[2] + origin[0],
            right[1] * vertex[0] + up[1] * vertex[1] + forward[1] * vertex[2] + origin[1],
            right[2] * vertex[0] + up[2] * vertex[1] + forward[2] * vertex[2] + origin[2],
        };
    } else {
        const double pitch = degrees_to_radians(number_or(brush.get("pitch_degrees"), number_or(brush.get("pitch"), 0.0)));
        const double yaw = degrees_to_radians(number_or(brush.get("yaw_degrees"), number_or(brush.get("yaw"), 0.0)));
        const Vec3 pan = vec3_or(brush.get("pan"), {
            number_or(brush.get("pan_x"), 0.0),
            number_or(brush.get("pan_y"), 0.0),
            number_or(brush.get("pan_z"), 0.0),
        });

        const double cp = std::cos(pitch);
        const double sp = std::sin(pitch);
        const double cy = std::cos(yaw);
        const double sy = std::sin(yaw);
        const Vec3 right{cy, sp * sy, cp * sy};
        const Vec3 up{0.0, cp, -sp};
        const Vec3 forward{-sy, sp * cy, cp * cy};
        world = {
            right[0] * vertex[0] + up[0] * vertex[1] + forward[0] * vertex[2] + pan[0],
            right[1] * vertex[0] + up[1] * vertex[1] + forward[1] * vertex[2] + pan[1],
            right[2] * vertex[0] + up[2] * vertex[1] + forward[2] * vertex[2] + pan[2],
        };
    }
    const double camera_z = world[2] + distance;
    if (!std::isfinite(camera_z) || camera_z < 0.05 || camera_z > 100.0) {
        return false;
    }
    const double tan_half_fov = std::tan(degrees_to_radians(fov) * 0.5);
    const double aspect = projection.viewport_width / projection.viewport_height;
    if (!std::isfinite(tan_half_fov) || std::abs(tan_half_fov) <= 1e-12 || !std::isfinite(aspect) || aspect <= 0.0) {
        return false;
    }
    const double clip_x = world[0] / (aspect * tan_half_fov * camera_z);
    const double clip_y = world[1] / (tan_half_fov * camera_z);
    if (!std::isfinite(clip_x) || !std::isfinite(clip_y)) {
        return false;
    }
    screen_x = projection.viewport_x + (clip_x * 0.5 + 0.5) * projection.viewport_width;
    screen_y = projection.viewport_y + (0.5 - clip_y * 0.5) * projection.viewport_height;
    if (depth_z != nullptr) {
        *depth_z = 0.0;
    }
    return std::isfinite(screen_x) && std::isfinite(screen_y);
}

bool mesh_editor_project_screen_brush_vertex(
    const JsonValue& brush,
    const Vec3& vertex,
    double& screen_x,
    double& screen_y
) {
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(brush);
    return mesh_editor_project_screen_brush_vertex_with_projection(brush, projection, vertex, screen_x, screen_y);
}

bool mesh_editor_ray_intersects_triangle(
    const MeshEditorScreenRay& ray,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c,
    double& distance
) {
    auto cross = [](const Vec3& left, const Vec3& right) -> Vec3 {
        return {
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        };
    };
    const Vec3 edge1 = sub_vec3(b, a);
    const Vec3 edge2 = sub_vec3(c, a);
    const Vec3 pvec = cross(ray.direction, edge2);
    const double determinant = dot_vec3(edge1, pvec);
    if (!std::isfinite(determinant) || std::abs(determinant) <= 1e-10) {
        return false;
    }
    const double inverse_determinant = 1.0 / determinant;
    const Vec3 tvec = sub_vec3(ray.origin, a);
    const double u = dot_vec3(tvec, pvec) * inverse_determinant;
    if (u < -1e-8 || u > 1.0 + 1e-8) {
        return false;
    }
    const Vec3 qvec = cross(tvec, edge1);
    const double v = dot_vec3(ray.direction, qvec) * inverse_determinant;
    if (v < -1e-8 || u + v > 1.0 + 1e-8) {
        return false;
    }
    const double t = dot_vec3(edge2, qvec) * inverse_determinant;
    if (!std::isfinite(t) || t < 0.0) {
        return false;
    }
    distance = t;
    return true;
}

bool mesh_editor_ray_segment_distance(
    const MeshEditorScreenRay& ray,
    const Vec3& a,
    const Vec3& b,
    double& distance,
    Vec3& closest_segment_point
) {
    const Vec3 segment = sub_vec3(b, a);
    const double segment_length_sq = dot_vec3(segment, segment);
    if (!std::isfinite(segment_length_sq) || segment_length_sq <= 1e-16) {
        const double ray_t = std::max(0.0, dot_vec3(ray.direction, sub_vec3(a, ray.origin)));
        const Vec3 closest_ray = add_vec3(ray.origin, scale_vec3(ray.direction, ray_t));
        closest_segment_point = a;
        distance = length_vec3(sub_vec3(closest_ray, a));
        return std::isfinite(distance);
    }
    const Vec3 origin_to_a = sub_vec3(ray.origin, a);
    const double ray_a = dot_vec3(ray.direction, ray.direction);
    const double ray_segment = dot_vec3(ray.direction, segment);
    const double ray_origin_to_a = dot_vec3(ray.direction, origin_to_a);
    const double segment_origin_to_a = dot_vec3(segment, origin_to_a);
    const double denom = ray_a * segment_length_sq - ray_segment * ray_segment;
    double ray_t = 0.0;
    if (std::abs(denom) > 1e-12 && std::isfinite(denom)) {
        ray_t = std::max(0.0, (ray_segment * segment_origin_to_a - ray_origin_to_a * segment_length_sq) / denom);
    }
    double segment_t = (ray_segment * ray_t + segment_origin_to_a) / segment_length_sq;
    if (segment_t < 0.0) {
        segment_t = 0.0;
        ray_t = std::max(0.0, -ray_origin_to_a / std::max(ray_a, 1e-16));
    } else if (segment_t > 1.0) {
        segment_t = 1.0;
        ray_t = std::max(0.0, (ray_segment - ray_origin_to_a) / std::max(ray_a, 1e-16));
    }
    const Vec3 closest_ray = add_vec3(ray.origin, scale_vec3(ray.direction, ray_t));
    closest_segment_point = add_vec3(a, scale_vec3(segment, segment_t));
    distance = length_vec3(sub_vec3(closest_ray, closest_segment_point));
    return std::isfinite(distance)
        && std::isfinite(closest_segment_point[0])
        && std::isfinite(closest_segment_point[1])
        && std::isfinite(closest_segment_point[2]);
}

int mesh_editor_pick_source_with_screen_ray(
    const MeshEditorSession* session,
    const JsonValue& brush,
    const MeshEditorScreenBrushProjection& projection
) {
    if (session == nullptr) {
        return -1;
    }
    int best_source_index = -1;
    double best_distance = std::numeric_limits<double>::infinity();
    for (const auto& entry : mesh_editor_submeshes(*session)) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        JsonValue index_value;
        index_value.type = JsonValue::Type::Number;
        index_value.number_value = static_cast<double>(entry.first);
        item.object_value["index"] = index_value;
        if (!mesh_editor_screen_brush_submesh_allowed(item, brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
        MeshEditorScreenRay ray;
        if (!mesh_editor_screen_ray_from_projection(brush, entry_projection, ray)) {
            continue;
        }
        for (const std::array<int, 3>& face : entry.second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                continue;
            }
            double distance = 0.0;
            if (!mesh_editor_ray_intersects_triangle(
                    ray,
                    entry.second.vertices[static_cast<std::size_t>(face[0])],
                    entry.second.vertices[static_cast<std::size_t>(face[1])],
                    entry.second.vertices[static_cast<std::size_t>(face[2])],
                    distance)) {
                continue;
            }
            if (distance < best_distance) {
                best_distance = distance;
                best_source_index = entry.first;
            }
        }
    }
    return best_source_index;
}

double mesh_editor_screen_segment_distance(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by
) {
    const double vx = bx - ax;
    const double vy = by - ay;
    const double length_sq = vx * vx + vy * vy;
    if (length_sq <= 1.0e-12) {
        return std::hypot(px - ax, py - ay);
    }
    const double t = std::clamp(((px - ax) * vx + (py - ay) * vy) / length_sq, 0.0, 1.0);
    const double closest_x = ax + vx * t;
    const double closest_y = ay + vy * t;
    return std::hypot(px - closest_x, py - closest_y);
}

double mesh_editor_screen_edge_function(double ax, double ay, double bx, double by, double cx, double cy) {
    return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax);
}

double mesh_editor_screen_triangle_distance(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by,
    double cx,
    double cy,
    double* out_w0 = nullptr,
    double* out_w1 = nullptr,
    double* out_w2 = nullptr
) {
    const double area = mesh_editor_screen_edge_function(ax, ay, bx, by, cx, cy);
    if (std::abs(area) > 1.0e-12) {
        const double w0 = mesh_editor_screen_edge_function(bx, by, cx, cy, px, py) / area;
        const double w1 = mesh_editor_screen_edge_function(cx, cy, ax, ay, px, py) / area;
        const double w2 = mesh_editor_screen_edge_function(ax, ay, bx, by, px, py) / area;
        if (out_w0 != nullptr) *out_w0 = w0;
        if (out_w1 != nullptr) *out_w1 = w1;
        if (out_w2 != nullptr) *out_w2 = w2;
        if (w0 >= -0.001 && w1 >= -0.001 && w2 >= -0.001) {
            return 0.0;
        }
    } else {
        if (out_w0 != nullptr) *out_w0 = 1.0;
        if (out_w1 != nullptr) *out_w1 = 0.0;
        if (out_w2 != nullptr) *out_w2 = 0.0;
    }
    return std::min({
        mesh_editor_screen_segment_distance(px, py, ax, ay, bx, by),
        mesh_editor_screen_segment_distance(px, py, bx, by, cx, cy),
        mesh_editor_screen_segment_distance(px, py, cx, cy, ax, ay),
    });
}

struct MeshEditorScreenBrushDepthMask {
    bool valid = false;
    int width = 0;
    int height = 0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    double scale_x = 1.0;
    double scale_y = 1.0;
    std::vector<double> depths;
};

MeshEditorScreenBrushDepthMask mesh_editor_screen_brush_depth_mask(
    const MeshEditorSession* session,
    const JsonValue& brush
) {
    MeshEditorScreenBrushDepthMask mask;
    if (session == nullptr) {
        return mask;
    }
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(brush);
    if (!projection.has_world_view_projection && projection.source_world_view_projections.empty()) {
        return mask;
    }
    constexpr double kMaxDepthMaskDimension = 1024.0;
    const double scale = std::min(1.0, kMaxDepthMaskDimension / std::max(projection.viewport_width, projection.viewport_height));
    mask.valid = true;
    mask.width = std::max(1, static_cast<int>(std::ceil(projection.viewport_width * scale)));
    mask.height = std::max(1, static_cast<int>(std::ceil(projection.viewport_height * scale)));
    mask.viewport_x = projection.viewport_x;
    mask.viewport_y = projection.viewport_y;
    mask.scale_x = static_cast<double>(mask.width) / projection.viewport_width;
    mask.scale_y = static_cast<double>(mask.height) / projection.viewport_height;
    mask.depths.assign(
        static_cast<std::size_t>(mask.width) * static_cast<std::size_t>(mask.height),
        std::numeric_limits<double>::infinity()
    );

    auto rasterize_triangle = [&](const Vec3& p0, const Vec3& p1, const Vec3& p2) {
        const double area = mesh_editor_screen_edge_function(p0[0], p0[1], p1[0], p1[1], p2[0], p2[1]);
        if (std::abs(area) <= 1.0e-12) {
            return;
        }
        int min_x = static_cast<int>(std::floor(std::min({p0[0], p1[0], p2[0]})));
        int max_x = static_cast<int>(std::ceil(std::max({p0[0], p1[0], p2[0]})));
        int min_y = static_cast<int>(std::floor(std::min({p0[1], p1[1], p2[1]})));
        int max_y = static_cast<int>(std::ceil(std::max({p0[1], p1[1], p2[1]})));
        min_x = std::max(0, std::min(mask.width - 1, min_x));
        max_x = std::max(0, std::min(mask.width - 1, max_x));
        min_y = std::max(0, std::min(mask.height - 1, min_y));
        max_y = std::max(0, std::min(mask.height - 1, max_y));
        if (min_x > max_x || min_y > max_y) {
            return;
        }
        for (int py = min_y; py <= max_y; ++py) {
            const double y = static_cast<double>(py) + 0.5;
            for (int px = min_x; px <= max_x; ++px) {
                const double x = static_cast<double>(px) + 0.5;
                const double w0 = mesh_editor_screen_edge_function(p1[0], p1[1], p2[0], p2[1], x, y) / area;
                const double w1 = mesh_editor_screen_edge_function(p2[0], p2[1], p0[0], p0[1], x, y) / area;
                const double w2 = mesh_editor_screen_edge_function(p0[0], p0[1], p1[0], p1[1], x, y) / area;
                if (w0 < -0.001 || w1 < -0.001 || w2 < -0.001) {
                    continue;
                }
                const double depth = w0 * p0[2] + w1 * p1[2] + w2 * p2[2];
                if (!std::isfinite(depth)) {
                    continue;
                }
                const std::size_t offset = static_cast<std::size_t>(py) * static_cast<std::size_t>(mask.width)
                    + static_cast<std::size_t>(px);
                mask.depths[offset] = std::min(mask.depths[offset], depth);
            }
        }
    };

    for (const auto& entry : mesh_editor_submeshes(*session)) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        JsonValue index_value;
        index_value.type = JsonValue::Type::Number;
        index_value.number_value = static_cast<double>(entry.first);
        item.object_value["index"] = index_value;
        if (!mesh_editor_screen_brush_submesh_allowed(item, brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
        for (const std::array<int, 3>& face : entry.second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                continue;
            }
            Vec3 projected[3]{};
            bool valid = true;
            for (int corner = 0; corner < 3; ++corner) {
                double screen_x = 0.0;
                double screen_y = 0.0;
                double depth_z = 0.0;
                if (!mesh_editor_project_screen_brush_vertex_with_projection(
                        brush,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[static_cast<std::size_t>(corner)])],
                        screen_x,
                        screen_y,
                        &depth_z)) {
                    valid = false;
                    break;
                }
                projected[corner] = {
                    (screen_x - mask.viewport_x) * mask.scale_x,
                    (screen_y - mask.viewport_y) * mask.scale_y,
                    depth_z,
                };
            }
            if (valid) {
                rasterize_triangle(projected[0], projected[1], projected[2]);
            }
        }
    }
    return mask;
}

bool mesh_editor_screen_brush_depth_visible(
    const MeshEditorScreenBrushDepthMask* mask,
    double screen_x,
    double screen_y,
    double depth_z
) {
    if (mask == nullptr || !mask->valid || mask->width <= 0 || mask->height <= 0 || mask->depths.empty()) {
        return true;
    }
    const int x = static_cast<int>(std::floor((screen_x - mask->viewport_x) * mask->scale_x));
    const int y = static_cast<int>(std::floor((screen_y - mask->viewport_y) * mask->scale_y));
    if (x < 0 || y < 0 || x >= mask->width || y >= mask->height) {
        return false;
    }
    const std::size_t offset = static_cast<std::size_t>(y) * static_cast<std::size_t>(mask->width)
        + static_cast<std::size_t>(x);
    if (offset >= mask->depths.size()) {
        return true;
    }
    const double front_depth = mask->depths[offset];
    if (!std::isfinite(front_depth) || !std::isfinite(depth_z)) {
        return true;
    }
    return depth_z <= front_depth + 0.0035;
}

std::map<int, double> screen_brush_vertex_weights_native(
    const JsonValue& item,
    const std::vector<Vec3>& vertices,
    const std::set<int>* allowed,
    const std::string& falloff,
    const JsonValue* raw_brush,
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr
) {
    std::map<int, double> weights;
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return weights;
    }
    const JsonValue* raw_x = raw_brush->get("x");
    if (raw_x == nullptr) raw_x = raw_brush->get("cursor_x");
    if (raw_x == nullptr) raw_x = raw_brush->get("screen_x");
    const JsonValue* raw_y = raw_brush->get("y");
    if (raw_y == nullptr) raw_y = raw_brush->get("cursor_y");
    if (raw_y == nullptr) raw_y = raw_brush->get("screen_y");
    if (raw_x == nullptr || raw_y == nullptr || !mesh_editor_screen_brush_submesh_allowed(item, *raw_brush)) {
        return weights;
    }
    const double cursor_x = number_or(raw_x, 0.0);
    const double cursor_y = number_or(raw_y, 0.0);
    const double radius_pixels = std::max(
        0.0,
        number_or(raw_brush->get("radius_pixels"), number_or(raw_brush->get("brush_radius_pixels"), number_or(raw_brush->get("pixels"), 0.0)))
    );
    if (!std::isfinite(cursor_x) || !std::isfinite(cursor_y) || radius_pixels <= 1e-8) {
        return weights;
    }
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(*raw_brush);
    const int source_submesh_index = int_or(item.get("index"), -1);
    const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, source_submesh_index);
    auto add_weight = [&](int index) {
        if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
            return;
        }
        double screen_x = 0.0;
        double screen_y = 0.0;
        double depth_z = 0.0;
        if (!mesh_editor_project_screen_brush_vertex_with_projection(
                *raw_brush,
                entry_projection,
                vertices[static_cast<std::size_t>(index)],
                screen_x,
                screen_y,
                depth_mask != nullptr ? &depth_z : nullptr)) {
            return;
        }
        if (!mesh_editor_screen_brush_depth_visible(depth_mask, screen_x, screen_y, depth_z)) {
            return;
        }
        const double distance_pixels = std::hypot(cursor_x - screen_x, cursor_y - screen_y);
        if (distance_pixels > radius_pixels) {
            return;
        }
        const double weight = std::max(
            distance_pixels <= 1e-8 ? 1.0 : 0.0,
            brush_falloff_weight(distance_pixels, radius_pixels, falloff)
        );
        if (weight > 0.0) {
            weights[index] = std::max(weights[index], weight);
        }
    };
    if (allowed != nullptr) {
        for (const int index : *allowed) {
            add_weight(index);
        }
        return weights;
    }
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        add_weight(static_cast<int>(index));
    }
    return weights;
}

bool mesh_editor_screen_brush_projection_unresolved_for_item(const JsonValue& item, const JsonValue* raw_brush) {
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return false;
    }
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(*raw_brush);
    const int source_submesh_index = int_or(item.get("index"), -1);
    return mesh_editor_projection_for_submesh(projection, source_submesh_index).projection_payload_unresolved;
}

const MeshEditorScreenBrushDepthMask* mesh_editor_screen_brush_depth_mask_for_edit(
    const JsonValue& item,
    const JsonValue& edit,
    const JsonValue* raw_brush,
    MeshEditorScreenBrushDepthMask& storage
) {
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return nullptr;
    }
    const std::string depth_mode = lower_ascii(string_or(
        edit.get("selection_depth_mode"),
        string_or(edit.get("depth_mode"), string_or(raw_brush->get("selection_depth_mode"), string_or(raw_brush->get("depth_mode"), "xray")))
    ));
    if (depth_mode == "xray") {
        return nullptr;
    }
    const MeshEditorSession* session = mesh_editor_session_for_item(item);
    if (session == nullptr) {
        return nullptr;
    }
    storage = mesh_editor_screen_brush_depth_mask(session, *raw_brush);
    return storage.valid ? &storage : nullptr;
}

std::map<int, int> mirror_pairs_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::map<int, int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        const int left = int_or(&item.array_value[0], -1);
        const int right = int_or(&item.array_value[1], -1);
        if (left >= 0 && right >= 0
            && static_cast<std::size_t>(left) < vertex_count
            && static_cast<std::size_t>(right) < vertex_count) {
            result[left] = right;
        }
    }
    return result;
}
