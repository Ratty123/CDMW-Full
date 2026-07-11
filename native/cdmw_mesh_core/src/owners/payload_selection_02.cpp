double screen_drag_axis_delta(
    const JsonValue& value,
    const std::string& short_key,
    const std::string& pixel_key,
    const std::string& start_key,
    const std::string& end_key
) {
    if (const JsonValue* delta = value.get(pixel_key)) {
        return number_or(delta, 0.0);
    }
    if (const JsonValue* delta = value.get(short_key)) {
        return number_or(delta, 0.0);
    }
    const double start = number_or(value.get(start_key), 0.0);
    return number_or(value.get(end_key), start) - start;
}

double mesh_editor_screen_units_per_pixel(const JsonValue& value) {
    double units_per_pixel = number_or(value.get("units_per_pixel"), 0.0);
    if (units_per_pixel > 0.0) {
        return units_per_pixel;
    }
    const double distance = std::max(number_or(value.get("distance"), 0.0), 0.1);
    const double viewport_height = std::max(number_or(value.get("viewport_height"), 0.0), 1.0);
    const double fov = std::max(number_or(value.get("vertical_fov_degrees"), 45.0), 1e-6);
    return (2.0 * distance * std::tan(degrees_to_radians(fov) * 0.5)) / viewport_height;
}

bool project_vertex_with_matrix_depth(
    const std::array<double, 16>& matrix,
    const Vec3& vertex,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    double& screen_x,
    double& screen_y,
    double& depth_z
) {
    const double clip_x = vertex[0] * matrix[0] + vertex[1] * matrix[4] + vertex[2] * matrix[8] + matrix[12];
    const double clip_y = vertex[0] * matrix[1] + vertex[1] * matrix[5] + vertex[2] * matrix[9] + matrix[13];
    const double clip_z = vertex[0] * matrix[2] + vertex[1] * matrix[6] + vertex[2] * matrix[10] + matrix[14];
    const double clip_w = vertex[0] * matrix[3] + vertex[1] * matrix[7] + vertex[2] * matrix[11] + matrix[15];
    if (!std::isfinite(clip_x) || !std::isfinite(clip_y) || !std::isfinite(clip_z) || !std::isfinite(clip_w)) {
        return false;
    }
    if (std::abs(clip_w) <= 1e-12) {
        return false;
    }
    const double ndc_x = clip_x / clip_w;
    const double ndc_y = clip_y / clip_w;
    const double ndc_z = clip_z / clip_w;
    if (!std::isfinite(ndc_x) || !std::isfinite(ndc_y) || !std::isfinite(ndc_z)) {
        return false;
    }
    if (ndc_z < 0.0 || ndc_z > 1.0) {
        return false;
    }
    screen_x = viewport_x + (ndc_x * 0.5 + 0.5) * viewport_width;
    screen_y = viewport_y + (0.5 - ndc_y * 0.5) * viewport_height;
    depth_z = ndc_z;
    return std::isfinite(screen_x) && std::isfinite(screen_y) && std::isfinite(depth_z);
}

bool project_vertex_with_matrix(
    const std::array<double, 16>& matrix,
    const Vec3& vertex,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    double& screen_x,
    double& screen_y
) {
    double depth_z = 0.0;
    return project_vertex_with_matrix_depth(
        matrix,
        vertex,
        viewport_x,
        viewport_y,
        viewport_width,
        viewport_height,
        screen_x,
        screen_y,
        depth_z
    );
}

bool unproject_screen_point_with_matrix_inverse(
    const std::array<double, 16>& inverse_matrix,
    double screen_x,
    double screen_y,
    double depth_z,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    Vec3& point
) {
    if (viewport_width <= 0.0 || viewport_height <= 0.0) {
        return false;
    }
    const double ndc_x = ((screen_x - viewport_x) / viewport_width - 0.5) * 2.0;
    const double ndc_y = (0.5 - (screen_y - viewport_y) / viewport_height) * 2.0;
    const double world_x = ndc_x * inverse_matrix[0] + ndc_y * inverse_matrix[4] + depth_z * inverse_matrix[8] + inverse_matrix[12];
    const double world_y = ndc_x * inverse_matrix[1] + ndc_y * inverse_matrix[5] + depth_z * inverse_matrix[9] + inverse_matrix[13];
    const double world_z = ndc_x * inverse_matrix[2] + ndc_y * inverse_matrix[6] + depth_z * inverse_matrix[10] + inverse_matrix[14];
    const double world_w = ndc_x * inverse_matrix[3] + ndc_y * inverse_matrix[7] + depth_z * inverse_matrix[11] + inverse_matrix[15];
    if (!std::isfinite(world_x) || !std::isfinite(world_y) || !std::isfinite(world_z)
        || !std::isfinite(world_w) || std::abs(world_w) <= 1e-12) {
        return false;
    }
    point = {world_x / world_w, world_y / world_w, world_z / world_w};
    return std::isfinite(point[0]) && std::isfinite(point[1]) && std::isfinite(point[2]);
}

bool mesh_editor_screen_drag_matrix_delta(
    const JsonValue& value,
    double dx,
    double dy,
    double units_per_pixel,
    Vec3& result
) {
    std::array<double, 16> camera_world{};
    if (!matrix4x4_from_json(value.get("camera_world"), camera_world)) {
        return false;
    }
    const Vec3 right{camera_world[0], camera_world[1], camera_world[2]};
    const Vec3 up{camera_world[4], camera_world[5], camera_world[6]};
    for (const double component : {right[0], right[1], right[2], up[0], up[1], up[2]}) {
        if (!std::isfinite(component)) {
            return false;
        }
    }
    result = {
        (right[0] * dx - up[0] * dy) * units_per_pixel,
        (right[1] * dx - up[1] * dy) * units_per_pixel,
        (right[2] * dx - up[2] * dy) * units_per_pixel,
    };
    return std::isfinite(result[0]) && std::isfinite(result[1]) && std::isfinite(result[2]);
}

double mesh_editor_screen_radius_pixels(const JsonValue& value) {
    return std::max(
        0.0,
        number_or(value.get("radius_pixels"), number_or(value.get("brush_radius_pixels"), number_or(value.get("pixels"), 0.0)))
    );
}

double mesh_editor_screen_radius_units(const JsonValue* value) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    const double pixels = mesh_editor_screen_radius_pixels(*value);
    return pixels * mesh_editor_screen_units_per_pixel(*value);
}

int mesh_editor_source_projection_override_index(const JsonValue& item) {
    if (item.type != JsonValue::Type::Object) {
        return -1;
    }
    return int_or(
        item.get("source_submesh_index"),
        int_or(item.get("submesh_index"), int_or(item.get("index"), -1))
    );
}

bool mesh_editor_has_source_projection_override(const JsonValue* value, int source_submesh_index) {
    if (value == nullptr || value->type != JsonValue::Type::Object || source_submesh_index < 0) {
        return false;
    }
    for (const char* key : {
             "source_submesh_world_view_projections",
             "source_world_view_projections",
             "source_submesh_world_transforms",
             "source_world_transforms",
         }) {
        const JsonValue* overrides = value->get(key);
        if (overrides == nullptr) {
            continue;
        }
        if (overrides->type != JsonValue::Type::Array) {
            return true;
        }
        for (const JsonValue& item : overrides->array_value) {
            if (mesh_editor_source_projection_override_index(item) == source_submesh_index) {
                return true;
            }
        }
    }
    return false;
}

bool mesh_editor_source_world_view_projection_from_json(
    const JsonValue* value,
    int source_submesh_index,
    std::array<double, 16>& world_view_projection
) {
    if (value == nullptr || value->type != JsonValue::Type::Object || source_submesh_index < 0) {
        return false;
    }
    for (const char* key : {"source_submesh_world_view_projections", "source_world_view_projections"}) {
        const JsonValue* overrides = value->get(key);
        if (overrides == nullptr || overrides->type != JsonValue::Type::Array) {
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int item_source = mesh_editor_source_projection_override_index(item);
            if (item_source == source_submesh_index
                && matrix4x4_from_json(item.get("world_view_projection"), world_view_projection)) {
                return true;
            }
        }
    }
    std::array<double, 16> base_world_view_projection{};
    if (!matrix4x4_from_json(value->get("world_view_projection"), base_world_view_projection)) {
        return false;
    }
    for (const char* key : {"source_submesh_world_transforms", "source_world_transforms"}) {
        const JsonValue* overrides = value->get(key);
        if (overrides == nullptr || overrides->type != JsonValue::Type::Array) {
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int item_source = mesh_editor_source_projection_override_index(item);
            std::array<double, 16> source_world_transform{};
            if (item_source == source_submesh_index && matrix4x4_from_transform_json(item, source_world_transform)) {
                world_view_projection = matrix4x4_multiply(source_world_transform, base_world_view_projection);
                return true;
            }
        }
    }
    return false;
}

bool mesh_editor_world_view_projection_from_json(
    const JsonValue* value,
    int source_submesh_index,
    std::array<double, 16>& world_view_projection
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return false;
    }
    const bool has_base_projection = matrix4x4_from_json(value->get("world_view_projection"), world_view_projection);
    const bool has_source_projection = mesh_editor_source_world_view_projection_from_json(
        value,
        source_submesh_index,
        world_view_projection
    );
    if (has_source_projection) {
        return true;
    }
    if (mesh_editor_has_source_projection_override(value, source_submesh_index)) {
        return false;
    }
    return has_base_projection;
}

bool mesh_editor_has_projection_payload(const JsonValue* value, int source_submesh_index) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return false;
    }
    if (value->get("world_view_projection") != nullptr) {
        return true;
    }
    for (const char* key : {
             "source_submesh_world_view_projections",
             "source_world_view_projections",
             "source_submesh_world_transforms",
             "source_world_transforms",
         }) {
        if (value->get(key) != nullptr) {
            return true;
        }
    }
    return false;
}

bool mesh_editor_projection_center_depth(
    const JsonValue& value,
    const Vec3& center,
    int source_submesh_index,
    std::array<double, 16>& inverse_matrix,
    double& center_x,
    double& center_y,
    double& depth_z,
    double& viewport_x,
    double& viewport_y,
    double& viewport_width,
    double& viewport_height
) {
    std::array<double, 16> world_view_projection{};
    if (!mesh_editor_world_view_projection_from_json(&value, source_submesh_index, world_view_projection)
        || !matrix4x4_inverse(world_view_projection, inverse_matrix)) {
        return false;
    }
    viewport_width = std::max(number_or(value.get("viewport_width"), number_or(value.get("width"), 0.0)), 1.0);
    viewport_height = std::max(number_or(value.get("viewport_height"), number_or(value.get("height"), 0.0)), 1.0);
    viewport_x = number_or(value.get("viewport_x"), number_or(value.get("top_left_x"), 0.0));
    viewport_y = number_or(value.get("viewport_y"), number_or(value.get("top_left_y"), 0.0));
    return project_vertex_with_matrix_depth(
        world_view_projection,
        center,
        viewport_x,
        viewport_y,
        viewport_width,
        viewport_height,
        center_x,
        center_y,
        depth_z
    );
}

double mesh_editor_screen_units_per_pixel_from_projection(
    const JsonValue& value,
    const Vec3& center,
    int source_submesh_index
) {
    std::array<double, 16> inverse_matrix{};
    double center_x = 0.0;
    double center_y = 0.0;
    double depth_z = 0.0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    double viewport_width = 1.0;
    double viewport_height = 1.0;
    if (!mesh_editor_projection_center_depth(
            value,
            center,
            source_submesh_index,
            inverse_matrix,
            center_x,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height)) {
        return 0.0;
    }
    Vec3 origin{};
    Vec3 right_pixel{};
    Vec3 down_pixel{};
    if (!unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            center_x,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            origin)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            center_x + 1.0,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            right_pixel)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            center_x,
            center_y + 1.0,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            down_pixel)) {
        return 0.0;
    }
    double total = 0.0;
    int count = 0;
    for (const Vec3& point : {right_pixel, down_pixel}) {
        const double units = std::sqrt(
            (point[0] - origin[0]) * (point[0] - origin[0])
            + (point[1] - origin[1]) * (point[1] - origin[1])
            + (point[2] - origin[2]) * (point[2] - origin[2])
        );
        if (std::isfinite(units) && units > 1e-12) {
            total += units;
            ++count;
        }
    }
    return count > 0 ? total / static_cast<double>(count) : 0.0;
}

bool mesh_editor_screen_drag_projection_delta(
    const JsonValue& value,
    const Vec3& center,
    int source_submesh_index,
    Vec3& result
) {
    std::array<double, 16> inverse_matrix{};
    double center_x = 0.0;
    double center_y = 0.0;
    double depth_z = 0.0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    double viewport_width = 1.0;
    double viewport_height = 1.0;
    if (!mesh_editor_projection_center_depth(
            value,
            center,
            source_submesh_index,
            inverse_matrix,
            center_x,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height)) {
        return false;
    }
    const double dx = screen_drag_axis_delta(value, "dx", "delta_x_pixels", "start_x", "end_x");
    const double dy = screen_drag_axis_delta(value, "dy", "delta_y_pixels", "start_y", "end_y");
    const double start_x = number_or(value.get("start_x"), center_x);
    const double start_y = number_or(value.get("start_y"), center_y);
    const double end_x = number_or(value.get("end_x"), start_x + dx);
    const double end_y = number_or(value.get("end_y"), start_y + dy);
    Vec3 start_point{};
    Vec3 end_point{};
    if (!unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            start_x,
            start_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            start_point)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            end_x,
            end_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            end_point)) {
        return false;
    }
    result = {
        end_point[0] - start_point[0],
        end_point[1] - start_point[1],
        end_point[2] - start_point[2],
    };
    return std::isfinite(result[0]) && std::isfinite(result[1]) && std::isfinite(result[2]);
}

double mesh_editor_screen_pixels_per_unit_at_center(
    const JsonValue* value,
    const Vec3& center,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    std::array<double, 16> world_view_projection{};
    std::array<double, 16> camera_world{};
    const bool has_base_projection = matrix4x4_from_json(value->get("world_view_projection"), world_view_projection);
    const bool has_source_projection = mesh_editor_source_world_view_projection_from_json(
        value,
        source_submesh_index,
        world_view_projection
    );
    if ((!has_base_projection && !has_source_projection)
        || !matrix4x4_from_json(value->get("camera_world"), camera_world)) {
        return 0.0;
    }
    const double viewport_width = std::max(number_or(value->get("viewport_width"), number_or(value->get("width"), 0.0)), 1.0);
    const double viewport_height = std::max(number_or(value->get("viewport_height"), number_or(value->get("height"), 0.0)), 1.0);
    const double viewport_x = number_or(value->get("viewport_x"), number_or(value->get("top_left_x"), 0.0));
    const double viewport_y = number_or(value->get("viewport_y"), number_or(value->get("top_left_y"), 0.0));
    double center_x = 0.0;
    double center_y = 0.0;
    if (!project_vertex_with_matrix(world_view_projection, center, viewport_x, viewport_y, viewport_width, viewport_height, center_x, center_y)) {
        return 0.0;
    }
    const Vec3 right{camera_world[0], camera_world[1], camera_world[2]};
    const Vec3 up{camera_world[4], camera_world[5], camera_world[6]};
    double density_total = 0.0;
    int density_count = 0;
    auto add_density = [&](const Vec3& axis) {
        for (double component : axis) {
            if (!std::isfinite(component)) {
                return;
            }
        }
        const Vec3 endpoint{center[0] + axis[0], center[1] + axis[1], center[2] + axis[2]};
        double endpoint_x = 0.0;
        double endpoint_y = 0.0;
        if (!project_vertex_with_matrix(
                world_view_projection,
                endpoint,
                viewport_x,
                viewport_y,
                viewport_width,
                viewport_height,
                endpoint_x,
                endpoint_y)) {
            return;
        }
        const double pixels_per_unit = std::hypot(endpoint_x - center_x, endpoint_y - center_y);
        if (std::isfinite(pixels_per_unit) && pixels_per_unit > 1e-8) {
            density_total += pixels_per_unit;
            ++density_count;
        }
    };
    add_density(right);
    add_density(up);
    if (density_count <= 0) {
        return 0.0;
    }
    return density_total / static_cast<double>(density_count);
}

double mesh_editor_screen_units_per_pixel_at_center(
    const JsonValue* value,
    const Vec3& center,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    const double explicit_units = number_or(value->get("units_per_pixel"), 0.0);
    if (explicit_units > 0.0) {
        return explicit_units;
    }
    const double projection_units = mesh_editor_screen_units_per_pixel_from_projection(*value, center, source_submesh_index);
    if (projection_units > 1e-12) {
        return projection_units;
    }
    if (mesh_editor_has_projection_payload(value, source_submesh_index)) {
        return 0.0;
    }
    const double pixels_per_unit = mesh_editor_screen_pixels_per_unit_at_center(value, center, source_submesh_index);
    if (pixels_per_unit > 1e-8) {
        return 1.0 / pixels_per_unit;
    }
    return mesh_editor_screen_units_per_pixel(*value);
}

double mesh_editor_screen_radius_units_at_center(
    const JsonValue* value,
    const Vec3& center,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    const double pixels = mesh_editor_screen_radius_pixels(*value);
    if (pixels <= 1e-8) {
        return 0.0;
    }
    const double units_per_pixel = mesh_editor_screen_units_per_pixel_at_center(value, center, source_submesh_index);
    if (units_per_pixel <= 1e-12) {
        return 0.0;
    }
    return pixels * units_per_pixel;
}

Vec3 mesh_editor_screen_drag_delta(
    const JsonValue* value,
    const Vec3* center = nullptr,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return {0.0, 0.0, 0.0};
    }
    const double dx = screen_drag_axis_delta(*value, "dx", "delta_x_pixels", "start_x", "end_x");
    const double dy = screen_drag_axis_delta(*value, "dy", "delta_y_pixels", "start_y", "end_y");
    if (std::abs(dx) <= 1e-12 && std::abs(dy) <= 1e-12) {
        return {0.0, 0.0, 0.0};
    }
    if (center != nullptr) {
        Vec3 projection_delta{0.0, 0.0, 0.0};
        if (mesh_editor_screen_drag_projection_delta(*value, *center, source_submesh_index, projection_delta)) {
            return projection_delta;
        }
        if (mesh_editor_has_projection_payload(value, source_submesh_index)) {
            return {0.0, 0.0, 0.0};
        }
    }
    const double units_per_pixel = center != nullptr
        ? mesh_editor_screen_units_per_pixel_at_center(value, *center, source_submesh_index)
        : mesh_editor_screen_units_per_pixel(*value);
    Vec3 matrix_delta{0.0, 0.0, 0.0};
    if (mesh_editor_screen_drag_matrix_delta(*value, dx, dy, units_per_pixel, matrix_delta)) {
        return matrix_delta;
    }
    const double pitch = degrees_to_radians(number_or(value->get("pitch_degrees"), number_or(value->get("pitch"), 0.0)));
    const double yaw = degrees_to_radians(number_or(value->get("yaw_degrees"), number_or(value->get("yaw"), 0.0)));
    const double cp = std::cos(pitch);
    const double sp = std::sin(pitch);
    const double cy = std::cos(yaw);
    const double sy = std::sin(yaw);
    const Vec3 right{cy, sp * sy, cp * sy};
    const Vec3 up{0.0, cp, -sp};
    return {
        (right[0] * dx - up[0] * dy) * units_per_pixel,
        (right[1] * dx - up[1] * dy) * units_per_pixel,
        (right[2] * dx - up[2] * dy) * units_per_pixel,
    };
}

Vec3 add_screen_drag_delta(
    Vec3 value,
    const JsonValue* screen_drag,
    const Vec3* center = nullptr,
    int source_submesh_index = -1
) {
    const Vec3 delta = mesh_editor_screen_drag_delta(screen_drag, center, source_submesh_index);
    return {value[0] + delta[0], value[1] + delta[1], value[2] + delta[2]};
}

std::string transform_axis_constraint(const JsonValue& transform) {
    const std::string axis = lower_ascii(string_or(transform.get("axis"), string_or(transform.get("constraint_axis"), "")));
    return (axis == "x" || axis == "y" || axis == "z") ? axis : std::string();
}

Vec3 constrain_vec3_axis(Vec3 value, const std::string& axis, const Vec3& defaults) {
    if (axis.empty()) {
        return value;
    }
    return {
        axis == "x" ? value[0] : defaults[0],
        axis == "y" ? value[1] : defaults[1],
        axis == "z" ? value[2] : defaults[2],
    };
}

std::vector<Vec3> vertices_from_json(const JsonValue* value) {
    std::vector<Vec3> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            result.push_back({0.0, 0.0, 0.0});
            continue;
        }
        result.push_back({
            number_or(&item.array_value[0], 0.0),
            number_or(&item.array_value[1], 0.0),
            number_or(&item.array_value[2], 0.0),
        });
    }
    return result;
}

std::map<int, Vec3> indexed_vertices_from_json(const JsonValue* value, int vertex_count) {
    std::map<int, Vec3> vertices;
    if (value == nullptr || value->type != JsonValue::Type::Array || vertex_count <= 0) {
        return vertices;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        const int index = int_or(&item.array_value[0], -1);
        if (index < 0 || index >= vertex_count) {
            continue;
        }
        const JsonValue& position_value = item.array_value[1];
        if (position_value.type != JsonValue::Type::Array || position_value.array_value.size() < 3) {
            continue;
        }
        Vec3 position{
            number_or(&position_value.array_value[0], 0.0),
            number_or(&position_value.array_value[1], 0.0),
            number_or(&position_value.array_value[2], 0.0),
        };
        if (std::isfinite(position[0]) && std::isfinite(position[1]) && std::isfinite(position[2])) {
            vertices[index] = position;
        }
    }
    return vertices;
}

std::vector<Vec2> uvs_from_json(const JsonValue* value) {
    std::vector<Vec2> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            result.push_back({0.0, 0.0});
            continue;
        }
        result.push_back({
            number_or(&item.array_value[0], 0.0),
            number_or(&item.array_value[1], 0.0),
        });
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_json(const JsonValue* value, std::size_t vertex_count);

std::string binary_payload_path(const JsonValue* value) {
    if (value == nullptr) {
        return std::string();
    }
    if (value->type == JsonValue::Type::String) {
        return value->string_value;
    }
    if (value->type != JsonValue::Type::Object) {
        return std::string();
    }
    return string_or(value->get("path"), "");
}

std::vector<char> read_binary_payload(const JsonValue* value, std::size_t element_size, const std::string& label) {
    const std::string path = binary_payload_path(value);
    if (path.empty()) {
        return {};
    }
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) {
        throw std::runtime_error("cannot open binary " + label + " payload: " + path);
    }
    const std::streamoff size = input.tellg();
    if (size < 0 || (element_size > 0 && static_cast<std::uint64_t>(size) % element_size != 0)) {
        throw std::runtime_error("invalid binary " + label + " payload size");
    }
    std::vector<char> bytes(static_cast<std::size_t>(size));
    input.seekg(0, std::ios::beg);
    if (!bytes.empty() && !input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()))) {
        throw std::runtime_error("cannot read binary " + label + " payload");
    }
    return bytes;
}

std::vector<Vec3> vertices_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(double) * 3, "vec3");
    std::vector<Vec3> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / (sizeof(double) * 3);
    std::vector<double> raw(count * 3);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        const Vec3 item{raw[index * 3], raw[index * 3 + 1], raw[index * 3 + 2]};
        if (!std::isfinite(item[0]) || !std::isfinite(item[1]) || !std::isfinite(item[2])) {
            throw std::runtime_error("non-finite binary vec3 payload");
        }
        result.push_back(item);
    }
    return result;
}

std::vector<int> int_vector_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(std::int32_t), "int");
    std::vector<int> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / sizeof(std::int32_t);
    std::vector<std::int32_t> raw(count);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (const std::int32_t value_item : raw) {
        result.push_back(static_cast<int>(value_item));
    }
    return result;
}
