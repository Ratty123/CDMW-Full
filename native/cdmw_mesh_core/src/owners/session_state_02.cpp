std::map<int, double> mesh_editor_vertex_weights_from_group(const JsonValue& item) {
    std::map<int, double> weights;
    const std::vector<int> indices = mesh_editor_index_vector_from_json(mesh_editor_group_values(item, "vertices"));
    const JsonValue* binary = item.get("weights_binary");
    if (binary == nullptr) {
        binary = item.get("vertex_weights_binary");
    }
    if (binary == nullptr) {
        binary = item.get("source_vertex_weights_binary");
    }
    if (binary != nullptr) {
        const std::vector<double> values = double_vector_from_f32_or_f64_binary(binary);
        if (values.size() == indices.size()) {
            for (std::size_t offset = 0; offset < indices.size(); ++offset) {
                const int index = indices[offset];
                const double weight = std::max(0.0, std::min(1.0, values[offset]));
                if (index >= 0 && weight > 0.0) {
                    weights[index] = std::max(weights[index], weight);
                }
            }
        }
        return weights;
    }
    const JsonValue* raw_weights = item.get("weights");
    if (raw_weights == nullptr) {
        raw_weights = item.get("vertex_weights");
    }
    if (raw_weights == nullptr) {
        raw_weights = item.get("source_vertex_weights");
    }
    if (raw_weights == nullptr || raw_weights->type != JsonValue::Type::Array) {
        return weights;
    }
    for (std::size_t offset = 0; offset < raw_weights->array_value.size(); ++offset) {
        const JsonValue& raw = raw_weights->array_value[offset];
        int index = -1;
        double weight = 0.0;
        if (raw.type == JsonValue::Type::Array && raw.array_value.size() >= 2) {
            index = int_or(&raw.array_value[0], -1);
            weight = number_or(&raw.array_value[1], 0.0);
        } else if (offset < indices.size()) {
            index = indices[offset];
            weight = number_or(&raw, 0.0);
        }
        weight = std::max(0.0, std::min(1.0, weight));
        if (index >= 0 && weight > 0.0) {
            weights[index] = std::max(weights[index], weight);
        }
    }
    return weights;
}

void mesh_editor_read_index_groups(
    const JsonValue* value,
    const std::string& preferred_key,
    std::map<int, std::set<int>>& target
) {
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index < 0) {
                continue;
            }
            const std::set<int> indices = mesh_editor_indices_from_json(mesh_editor_group_values(item, preferred_key));
            if (!indices.empty()) {
                target[index] = indices;
            }
        }
        return;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const auto& entry : value->object_value) {
            int index = -1;
            if (!mesh_editor_key_to_index(entry.first, index)) {
                continue;
            }
            const JsonValue* values = &entry.second;
            if (entry.second.type == JsonValue::Type::Object) {
                values = mesh_editor_group_values(entry.second, preferred_key);
            }
            const std::set<int> indices = mesh_editor_indices_from_json(values);
            if (!indices.empty()) {
                target[index] = indices;
            }
        }
    }
}

void mesh_editor_read_vertex_weight_groups(
    const JsonValue* value,
    std::map<int, std::map<int, double>>& target
) {
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index < 0) {
                continue;
            }
            std::map<int, double> weights = mesh_editor_vertex_weights_from_group(item);
            if (!weights.empty()) {
                target[index] = std::move(weights);
            }
        }
        return;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const auto& entry : value->object_value) {
            int index = -1;
            if (!mesh_editor_key_to_index(entry.first, index) || entry.second.type != JsonValue::Type::Object) {
                continue;
            }
            std::map<int, double> weights = mesh_editor_vertex_weights_from_group(entry.second);
            if (!weights.empty()) {
                target[index] = std::move(weights);
            }
        }
    }
}

void mesh_editor_read_edge_groups(
    const JsonValue* value,
    std::map<int, std::set<std::array<int, 2>>>& target
) {
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index < 0) {
                continue;
            }
            const std::set<std::array<int, 2>> edges = mesh_editor_edges_from_json(mesh_editor_group_values(item, "edges"));
            if (!edges.empty()) {
                target[index] = edges;
            }
        }
        return;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const auto& entry : value->object_value) {
            int index = -1;
            if (!mesh_editor_key_to_index(entry.first, index)) {
                continue;
            }
            const std::set<std::array<int, 2>> edges = mesh_editor_edges_from_json(&entry.second);
            if (!edges.empty()) {
                target[index] = edges;
            }
        }
    }
}

void mesh_editor_prune_vertex_weights_to_selection(MeshEditorSelection& selection) {
    for (auto iter = selection.vertex_weights.begin(); iter != selection.vertex_weights.end();) {
        const auto selected = selection.vertices.find(iter->first);
        if (selected == selection.vertices.end()) {
            iter = selection.vertex_weights.erase(iter);
            continue;
        }
        for (auto weight_iter = iter->second.begin(); weight_iter != iter->second.end();) {
            if (selected->second.find(weight_iter->first) == selected->second.end()) {
                weight_iter = iter->second.erase(weight_iter);
            } else {
                ++weight_iter;
            }
        }
        if (iter->second.empty()) {
            iter = selection.vertex_weights.erase(iter);
        } else {
            ++iter;
        }
    }
}

bool mesh_editor_screen_region_contains(const JsonValue& region, double screen_x, double screen_y) {
    const std::string mode = lower_ascii(string_or(region.get("mode"), string_or(region.get("selection_mode"), "rectangle")));
    const std::vector<Vec2> points = vec2_array_from_json(region.get("points"));
    if (mode == "lasso" && points.size() >= 3) {
        return uv_point_in_polygon({screen_x, screen_y}, points);
    }
    const double start_x = number_or(region.get("start_x"), number_or(region.get("x0"), std::numeric_limits<double>::quiet_NaN()));
    const double start_y = number_or(region.get("start_y"), number_or(region.get("y0"), std::numeric_limits<double>::quiet_NaN()));
    const double end_x = number_or(region.get("end_x"), number_or(region.get("x1"), number_or(region.get("x"), std::numeric_limits<double>::quiet_NaN())));
    const double end_y = number_or(region.get("end_y"), number_or(region.get("y1"), number_or(region.get("y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(start_x) || !std::isfinite(start_y) || !std::isfinite(end_x) || !std::isfinite(end_y)) {
        return false;
    }
    return screen_x >= std::min(start_x, end_x)
        && screen_x <= std::max(start_x, end_x)
        && screen_y >= std::min(start_y, end_y)
        && screen_y <= std::max(start_y, end_y);
}

double mesh_editor_screen_orientation(const Vec2& a, const Vec2& b, const Vec2& c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

bool mesh_editor_screen_point_on_segment(const Vec2& point, const Vec2& a, const Vec2& b) {
    constexpr double epsilon = 1.0e-9;
    return std::abs(mesh_editor_screen_orientation(a, b, point)) <= epsilon
        && point[0] >= std::min(a[0], b[0]) - epsilon
        && point[0] <= std::max(a[0], b[0]) + epsilon
        && point[1] >= std::min(a[1], b[1]) - epsilon
        && point[1] <= std::max(a[1], b[1]) + epsilon;
}

bool mesh_editor_screen_segments_intersect(const Vec2& a, const Vec2& b, const Vec2& c, const Vec2& d) {
    const double ab_c = mesh_editor_screen_orientation(a, b, c);
    const double ab_d = mesh_editor_screen_orientation(a, b, d);
    const double cd_a = mesh_editor_screen_orientation(c, d, a);
    const double cd_b = mesh_editor_screen_orientation(c, d, b);
    if (((ab_c > 0.0 && ab_d < 0.0) || (ab_c < 0.0 && ab_d > 0.0))
        && ((cd_a > 0.0 && cd_b < 0.0) || (cd_a < 0.0 && cd_b > 0.0))) {
        return true;
    }
    return mesh_editor_screen_point_on_segment(c, a, b)
        || mesh_editor_screen_point_on_segment(d, a, b)
        || mesh_editor_screen_point_on_segment(a, c, d)
        || mesh_editor_screen_point_on_segment(b, c, d);
}

bool mesh_editor_screen_segment_intersection_point(
    const Vec2& a,
    const Vec2& b,
    const Vec2& c,
    const Vec2& d,
    Vec2& out_point
) {
    if (!mesh_editor_screen_segments_intersect(a, b, c, d)) {
        return false;
    }
    constexpr double epsilon = 1.0e-9;
    const double rx = b[0] - a[0];
    const double ry = b[1] - a[1];
    const double sx = d[0] - c[0];
    const double sy = d[1] - c[1];
    const double denom = rx * sy - ry * sx;
    if (std::abs(denom) > epsilon) {
        const double t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / denom;
        out_point = {a[0] + t * rx, a[1] + t * ry};
        return true;
    }
    for (const Vec2& point : {a, b, c, d}) {
        if (mesh_editor_screen_point_on_segment(point, a, b)
            && mesh_editor_screen_point_on_segment(point, c, d)) {
            out_point = point;
            return true;
        }
    }
    out_point = a;
    return true;
}

bool mesh_editor_screen_point_in_triangle(const Vec2& point, const Vec2& a, const Vec2& b, const Vec2& c) {
    constexpr double epsilon = 1.0e-9;
    const double ab = mesh_editor_screen_orientation(a, b, point);
    const double bc = mesh_editor_screen_orientation(b, c, point);
    const double ca = mesh_editor_screen_orientation(c, a, point);
    const bool has_negative = ab < -epsilon || bc < -epsilon || ca < -epsilon;
    const bool has_positive = ab > epsilon || bc > epsilon || ca > epsilon;
    return !(has_negative && has_positive);
}

bool mesh_editor_screen_triangle_depth_at(
    const Vec2& point,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c,
    double& out_depth
) {
    const Vec2 av{a[0], a[1]};
    const Vec2 bv{b[0], b[1]};
    const Vec2 cv{c[0], c[1]};
    const double area = mesh_editor_screen_orientation(av, bv, cv);
    if (std::abs(area) <= 1.0e-12) {
        return false;
    }
    const double w0 = mesh_editor_screen_orientation(bv, cv, point) / area;
    const double w1 = mesh_editor_screen_orientation(cv, av, point) / area;
    const double w2 = mesh_editor_screen_orientation(av, bv, point) / area;
    out_depth = w0 * a[2] + w1 * b[2] + w2 * c[2];
    return std::isfinite(out_depth);
}

std::vector<Vec2> mesh_editor_screen_region_boundary_points(const JsonValue& region) {
    const std::string mode = lower_ascii(string_or(region.get("mode"), string_or(region.get("selection_mode"), "rectangle")));
    const std::vector<Vec2> points = vec2_array_from_json(region.get("points"));
    if (mode == "lasso" && points.size() >= 3) {
        return points;
    }
    const double start_x = number_or(region.get("start_x"), number_or(region.get("x0"), std::numeric_limits<double>::quiet_NaN()));
    const double start_y = number_or(region.get("start_y"), number_or(region.get("y0"), std::numeric_limits<double>::quiet_NaN()));
    const double end_x = number_or(region.get("end_x"), number_or(region.get("x1"), number_or(region.get("x"), std::numeric_limits<double>::quiet_NaN())));
    const double end_y = number_or(region.get("end_y"), number_or(region.get("y1"), number_or(region.get("y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(start_x) || !std::isfinite(start_y) || !std::isfinite(end_x) || !std::isfinite(end_y)) {
        return {};
    }
    const double left = std::min(start_x, end_x);
    const double right = std::max(start_x, end_x);
    const double top = std::min(start_y, end_y);
    const double bottom = std::max(start_y, end_y);
    return {{left, top}, {right, top}, {right, bottom}, {left, bottom}};
}

bool mesh_editor_screen_region_segment_sample(
    const JsonValue& region,
    double ax,
    double ay,
    double bx,
    double by,
    Vec2& out_sample
) {
    if (!std::isfinite(ax) || !std::isfinite(ay) || !std::isfinite(bx) || !std::isfinite(by)) {
        return false;
    }
    if (mesh_editor_screen_region_contains(region, ax, ay)) {
        out_sample = {ax, ay};
        return true;
    }
    if (mesh_editor_screen_region_contains(region, bx, by)) {
        out_sample = {bx, by};
        return true;
    }
    const Vec2 a{ax, ay};
    const Vec2 b{bx, by};
    const std::string mode = lower_ascii(string_or(region.get("mode"), string_or(region.get("selection_mode"), "rectangle")));
    const std::vector<Vec2> points = vec2_array_from_json(region.get("points"));
    if (mode == "lasso" && points.size() >= 3) {
        for (std::size_t index = 0; index < points.size(); ++index) {
            if (mesh_editor_screen_segment_intersection_point(a, b, points[index], points[(index + 1) % points.size()], out_sample)) {
                return true;
            }
        }
        return false;
    }
    const double start_x = number_or(region.get("start_x"), number_or(region.get("x0"), std::numeric_limits<double>::quiet_NaN()));
    const double start_y = number_or(region.get("start_y"), number_or(region.get("y0"), std::numeric_limits<double>::quiet_NaN()));
    const double end_x = number_or(region.get("end_x"), number_or(region.get("x1"), number_or(region.get("x"), std::numeric_limits<double>::quiet_NaN())));
    const double end_y = number_or(region.get("end_y"), number_or(region.get("y1"), number_or(region.get("y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(start_x) || !std::isfinite(start_y) || !std::isfinite(end_x) || !std::isfinite(end_y)) {
        return false;
    }
    const double left = std::min(start_x, end_x);
    const double right = std::max(start_x, end_x);
    const double top = std::min(start_y, end_y);
    const double bottom = std::max(start_y, end_y);
    const Vec2 top_left{left, top};
    const Vec2 top_right{right, top};
    const Vec2 bottom_right{right, bottom};
    const Vec2 bottom_left{left, bottom};
    return mesh_editor_screen_segment_intersection_point(a, b, top_left, top_right, out_sample)
        || mesh_editor_screen_segment_intersection_point(a, b, top_right, bottom_right, out_sample)
        || mesh_editor_screen_segment_intersection_point(a, b, bottom_right, bottom_left, out_sample)
        || mesh_editor_screen_segment_intersection_point(a, b, bottom_left, top_left, out_sample);
}

bool mesh_editor_screen_region_segment_intersects(
    const JsonValue& region,
    double ax,
    double ay,
    double bx,
    double by
) {
    Vec2 sample{};
    return mesh_editor_screen_region_segment_sample(region, ax, ay, bx, by, sample);
}

bool mesh_editor_screen_region_triangle_intersects(
    const JsonValue& region,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c,
    Vec3& out_sample
) {
    if (!std::isfinite(a[0]) || !std::isfinite(a[1]) || !std::isfinite(a[2])
        || !std::isfinite(b[0]) || !std::isfinite(b[1]) || !std::isfinite(b[2])
        || !std::isfinite(c[0]) || !std::isfinite(c[1]) || !std::isfinite(c[2])) {
        return false;
    }
    const Vec2 av{a[0], a[1]};
    const Vec2 bv{b[0], b[1]};
    const Vec2 cv{c[0], c[1]};
    if (mesh_editor_screen_region_contains(region, av[0], av[1])) {
        out_sample = a;
        return true;
    }
    if (mesh_editor_screen_region_contains(region, bv[0], bv[1])) {
        out_sample = b;
        return true;
    }
    if (mesh_editor_screen_region_contains(region, cv[0], cv[1])) {
        out_sample = c;
        return true;
    }
    const std::vector<Vec2> points = mesh_editor_screen_region_boundary_points(region);
    for (const Vec2& point : points) {
        if (mesh_editor_screen_point_in_triangle(point, av, bv, cv)) {
            double depth = 0.0;
            if (mesh_editor_screen_triangle_depth_at(point, a, b, c, depth)) {
                out_sample = {point[0], point[1], depth};
                return true;
            }
        }
    }
    if (points.size() < 2) {
        return false;
    }
    const std::array<std::array<Vec2, 2>, 3> triangle_edges{{{av, bv}, {bv, cv}, {cv, av}}};
    for (std::size_t index = 0; index < points.size(); ++index) {
        const Vec2 region_a = points[index];
        const Vec2 region_b = points[(index + 1) % points.size()];
        for (const auto& edge : triangle_edges) {
            Vec2 hit{};
            if (!mesh_editor_screen_segment_intersection_point(region_a, region_b, edge[0], edge[1], hit)) {
                continue;
            }
            double depth = 0.0;
            if (mesh_editor_screen_triangle_depth_at(hit, a, b, c, depth)) {
                out_sample = {hit[0], hit[1], depth};
                return true;
            }
        }
    }
    return false;
}
