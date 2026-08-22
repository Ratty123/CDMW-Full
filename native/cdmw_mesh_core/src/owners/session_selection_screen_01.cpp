struct MeshEditorScreenBrushSelectionContext {
    const JsonValue& brush;
    std::string target_mode;
    std::string falloff;
    double x = 0.0;
    double y = 0.0;
    double radius_pixels = 0.0;
    bool has_screen_point = false;
    MeshEditorScreenBrushProjection projection;
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr;
};

bool mesh_editor_brush_face_screen_hit(
    const MeshSessionSubmesh& submesh,
    const std::array<int, 3>& face,
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection
);

void mesh_editor_select_brush_source(
    const MeshEditorSession& session,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushSelectionContext& context
) {
    if (!context.has_screen_point) {
        return;
    }
    int best_index = mesh_editor_pick_source_with_screen_ray(&session, context.brush, context.projection);
    if (best_index >= 0) {
        selection.source_indices.insert(best_index);
        return;
    }
    double best_distance = context.radius_pixels;
    for (const auto& entry : mesh_editor_submeshes(session)) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        item.object_value["index"] = mesh_editor_json_number(entry.first);
        if (!mesh_editor_screen_brush_submesh_allowed(item, context.brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection projection =
            mesh_editor_projection_for_submesh(context.projection, entry.first);
        for (const Vec3& vertex : entry.second.vertices) {
            double screen_x = 0.0;
            double screen_y = 0.0;
            double depth_z = 0.0;
            if (!mesh_editor_project_screen_brush_vertex_with_projection(
                    context.brush,
                    projection,
                    vertex,
                    screen_x,
                    screen_y,
                    context.depth_mask != nullptr ? &depth_z : nullptr)) {
                continue;
            }
            const double distance = std::hypot(context.x - screen_x, context.y - screen_y);
            if (distance >= best_distance
                || !mesh_editor_screen_brush_depth_visible(context.depth_mask, screen_x, screen_y, depth_z)) {
                continue;
            }
            best_distance = distance;
            best_index = entry.first;
        }
    }
    if (best_index >= 0) {
        selection.source_indices.insert(best_index);
    }
}

void mesh_editor_select_brush_sources(
    const MeshEditorSession& session,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushSelectionContext& context
) {
    if (!context.has_screen_point) {
        return;
    }
    for (const auto& entry : mesh_editor_submeshes(session)) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        item.object_value["index"] = mesh_editor_json_number(entry.first);
        if (!mesh_editor_screen_brush_submesh_allowed(item, context.brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection projection =
            mesh_editor_projection_for_submesh(context.projection, entry.first);
        for (const std::array<int, 3>& face : entry.second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                continue;
            }
            if (mesh_editor_brush_face_screen_hit(entry.second, face, context, projection)) {
                selection.source_indices.insert(entry.first);
                break;
            }
        }
    }
}

bool mesh_editor_brush_edge_ray_hit(
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection,
    const MeshEditorScreenRay& ray,
    int submesh_index,
    const Vec3& edge_start,
    const Vec3& edge_end
) {
    double ray_distance = 0.0;
    Vec3 hit{};
    const Vec3 midpoint = scale_vec3(add_vec3(edge_start, edge_end), 0.5);
    const double radius_world = std::max(
        mesh_editor_screen_radius_units_at_center(&context.brush, midpoint, submesh_index),
        1e-8
    );
    if (!mesh_editor_ray_segment_distance(ray, edge_start, edge_end, ray_distance, hit)
        || ray_distance > radius_world) {
        return false;
    }
    if (context.depth_mask == nullptr) {
        return true;
    }
    double x = 0.0;
    double y = 0.0;
    double depth = 0.0;
    return project_vertex_with_matrix_depth(
        projection.world_view_projection,
        hit,
        projection.viewport_x,
        projection.viewport_y,
        projection.viewport_width,
        projection.viewport_height,
        x,
        y,
        depth
    ) && mesh_editor_screen_brush_depth_visible(context.depth_mask, x, y, depth);
}

struct MeshEditorProjectedScreenSegment {
    double ax = 0.0;
    double ay = 0.0;
    double az = 0.0;
    double bx = 0.0;
    double by = 0.0;
    double bz = 0.0;
};

/// Projects a world segment, clipping it to the projectable depth window when
/// an endpoint falls outside it. An edge whose far end leaves the window used
/// to be rejected whole, so its visible span could never be brush-selected.
bool mesh_editor_project_screen_segment_clipped(
    const JsonValue& payload,
    const MeshEditorScreenBrushProjection& projection,
    const Vec3& start,
    const Vec3& end,
    bool need_depth,
    MeshEditorProjectedScreenSegment& out
) {
    const auto project = [&](const Vec3& vertex, double& x, double& y, double* z) {
        return mesh_editor_project_screen_brush_vertex_with_projection(payload, projection, vertex, x, y, z);
    };
    const bool start_ok = project(start, out.ax, out.ay, need_depth ? &out.az : nullptr);
    const bool end_ok = project(end, out.bx, out.by, need_depth ? &out.bz : nullptr);
    if (start_ok && end_ok) {
        return true;
    }
    const auto clip_toward = [&](Vec3 good, Vec3 bad, double& x, double& y, double* z) {
        for (int iteration = 0; iteration < 24; ++iteration) {
            const Vec3 mid = scale_vec3(add_vec3(good, bad), 0.5);
            double mid_x = 0.0;
            double mid_y = 0.0;
            double mid_z = 0.0;
            if (project(mid, mid_x, mid_y, need_depth ? &mid_z : nullptr)) {
                good = mid;
            } else {
                bad = mid;
            }
        }
        return project(good, x, y, z);
    };
    if (start_ok != end_ok) {
        const Vec3& good = start_ok ? start : end;
        const Vec3& bad = start_ok ? end : start;
        double* z = need_depth ? (start_ok ? &out.bz : &out.az) : nullptr;
        return start_ok
            ? clip_toward(good, bad, out.bx, out.by, z)
            : clip_toward(good, bad, out.ax, out.ay, z);
    }
    // Both ends outside: the segment may still cross the window.
    const Vec3 midpoint = scale_vec3(add_vec3(start, end), 0.5);
    double mid_x = 0.0;
    double mid_y = 0.0;
    double mid_z = 0.0;
    if (!project(midpoint, mid_x, mid_y, need_depth ? &mid_z : nullptr)) {
        return false;
    }
    return clip_toward(midpoint, start, out.ax, out.ay, need_depth ? &out.az : nullptr)
        && clip_toward(midpoint, end, out.bx, out.by, need_depth ? &out.bz : nullptr);
}

/// Cursor-vs-projected-segment test with the depth check sampled along the
/// segment's in-radius span. The depth mask is a rasterized approximation and
/// the edge lies on the very surface it is tested against, so a single
/// occluded sample must not hide a wire whose in-brush span is partly visible.
bool mesh_editor_brush_projected_segment_hit(
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorProjectedScreenSegment& segment
) {
    const double vx = segment.bx - segment.ax;
    const double vy = segment.by - segment.ay;
    const double length_sq = vx * vx + vy * vy;
    const double t = length_sq <= 1.0e-12
        ? 0.0
        : std::clamp(((context.x - segment.ax) * vx + (context.y - segment.ay) * vy) / length_sq, 0.0, 1.0);
    const double hit_x = segment.ax + vx * t;
    const double hit_y = segment.ay + vy * t;
    if (std::hypot(context.x - hit_x, context.y - hit_y) > context.radius_pixels) {
        return false;
    }
    if (context.depth_mask == nullptr) {
        return true;
    }
    double t_low = t;
    double t_high = t;
    if (length_sq > 1.0e-12) {
        const double b_half = (segment.ax - context.x) * vx + (segment.ay - context.y) * vy;
        const double c_term = (segment.ax - context.x) * (segment.ax - context.x)
            + (segment.ay - context.y) * (segment.ay - context.y)
            - context.radius_pixels * context.radius_pixels;
        const double discriminant = b_half * b_half - length_sq * c_term;
        if (discriminant >= 0.0) {
            const double root = std::sqrt(discriminant);
            t_low = std::clamp((-b_half - root) / length_sq, 0.0, 1.0);
            t_high = std::clamp((-b_half + root) / length_sq, 0.0, 1.0);
        }
    }
    for (int sample = 0; sample <= 4; ++sample) {
        const double tk = t_low + (t_high - t_low) * (static_cast<double>(sample) / 4.0);
        if (mesh_editor_screen_brush_depth_visible(
                context.depth_mask,
                segment.ax + vx * tk,
                segment.ay + vy * tk,
                segment.az + (segment.bz - segment.az) * tk)) {
            return true;
        }
    }
    return false;
}

bool mesh_editor_brush_edge_screen_hit(
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection,
    const Vec3& edge_start,
    const Vec3& edge_end
) {
    MeshEditorProjectedScreenSegment segment;
    if (!mesh_editor_project_screen_segment_clipped(
            context.brush, projection, edge_start, edge_end, context.depth_mask != nullptr, segment)) {
        return false;
    }
    return mesh_editor_brush_projected_segment_hit(context, segment);
}

void mesh_editor_select_brush_edges(
    int submesh_index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection,
    const MeshEditorScreenRay* ray
) {
    if (!context.has_screen_point) {
        return;
    }
    std::set<std::array<int, 2>>& selected = selection.edges[submesh_index];
    // Every projection this loop needs, computed once per vertex. Interior
    // edges are shared by two faces and each face names its three edges, so
    // the per-face-edge projection alone did six projections per face.
    const std::size_t vertex_count = submesh.vertices.size();
    const bool need_depth = context.depth_mask != nullptr;
    std::vector<std::array<double, 3>> projected(vertex_count);
    std::vector<char> projected_ok(vertex_count, 0);
    for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
        std::array<double, 3>& out = projected[vertex_index];
        projected_ok[vertex_index] = mesh_editor_project_screen_brush_vertex_with_projection(
            context.brush,
            projection,
            submesh.vertices[vertex_index],
            out[0],
            out[1],
            need_depth ? &out[2] : nullptr)
            ? 1
            : 0;
    }
    std::set<std::array<int, 2>> tested;
    for (const std::array<int, 3>& face : submesh.faces) {
        const std::array<std::array<int, 2>, 3> face_edges{{
            {face[0], face[1]}, {face[1], face[2]}, {face[2], face[0]},
        }};
        for (const std::array<int, 2>& raw_edge : face_edges) {
            if (raw_edge[0] < 0 || raw_edge[1] < 0 || raw_edge[0] == raw_edge[1]
                || static_cast<std::size_t>(raw_edge[0]) >= vertex_count
                || static_cast<std::size_t>(raw_edge[1]) >= vertex_count) {
                continue;
            }
            const std::array<int, 2> edge = edge_key(raw_edge[0], raw_edge[1]);
            if (selected.find(edge) != selected.end() || !tested.insert(edge).second) {
                continue;
            }
            const Vec3& start = submesh.vertices[static_cast<std::size_t>(edge[0])];
            const Vec3& end = submesh.vertices[static_cast<std::size_t>(edge[1])];
            bool hit = ray != nullptr && mesh_editor_brush_edge_ray_hit(
                context, projection, *ray, submesh_index, start, end
            );
            if (!hit) {
                const std::size_t index_a = static_cast<std::size_t>(edge[0]);
                const std::size_t index_b = static_cast<std::size_t>(edge[1]);
                if (projected_ok[index_a] && projected_ok[index_b]) {
                    const MeshEditorProjectedScreenSegment segment{
                        projected[index_a][0], projected[index_a][1], projected[index_a][2],
                        projected[index_b][0], projected[index_b][1], projected[index_b][2],
                    };
                    hit = mesh_editor_brush_projected_segment_hit(context, segment);
                } else if (projected_ok[index_a] || projected_ok[index_b]) {
                    hit = mesh_editor_brush_edge_screen_hit(context, projection, start, end);
                }
            }
            if (hit) {
                selected.insert(edge);
            }
        }
    }
    if (selected.empty()) {
        selection.edges.erase(submesh_index);
    }
}

bool mesh_editor_brush_face_ray_hit(
    const MeshSessionSubmesh& submesh,
    const std::array<int, 3>& face,
    const MeshEditorScreenRay& ray,
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection,
    bool& intersected
) {
    double ray_distance = 0.0;
    intersected = false;
    if (!mesh_editor_ray_intersects_triangle(
            ray,
            submesh.vertices[static_cast<std::size_t>(face[0])],
            submesh.vertices[static_cast<std::size_t>(face[1])],
            submesh.vertices[static_cast<std::size_t>(face[2])],
            ray_distance)) {
        return false;
    }
    intersected = true;
    if (context.depth_mask == nullptr) {
        return true;
    }
    const Vec3 hit = add_vec3(ray.origin, scale_vec3(ray.direction, ray_distance));
    double x = 0.0;
    double y = 0.0;
    double depth = 0.0;
    return project_vertex_with_matrix_depth(
        projection.world_view_projection,
        hit,
        projection.viewport_x,
        projection.viewport_y,
        projection.viewport_width,
        projection.viewport_height,
        x,
        y,
        depth
    ) && mesh_editor_screen_brush_depth_visible(context.depth_mask, x, y, depth);
}

bool mesh_editor_brush_face_screen_hit(
    const MeshSessionSubmesh& submesh,
    const std::array<int, 3>& face,
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection
) {
    std::array<double, 3> x{};
    std::array<double, 3> y{};
    std::array<double, 3> z{};
    for (int corner = 0; corner < 3; ++corner) {
        if (!mesh_editor_project_screen_brush_vertex_with_projection(
                context.brush,
                projection,
                submesh.vertices[static_cast<std::size_t>(face[corner])],
                x[corner],
                y[corner],
                context.depth_mask != nullptr ? &z[corner] : nullptr)) {
            return false;
        }
    }
    double w0 = 1.0;
    double w1 = 0.0;
    double w2 = 0.0;
    const double distance = mesh_editor_screen_triangle_distance(
        context.x, context.y, x[0], y[0], x[1], y[1], x[2], y[2], &w0, &w1, &w2
    );
    if (distance > context.radius_pixels) {
        return false;
    }
    const double hit_depth = w0 * z[0] + w1 * z[1] + w2 * z[2];
    const double centroid_x = (x[0] + x[1] + x[2]) / 3.0;
    const double centroid_y = (y[0] + y[1] + y[2]) / 3.0;
    const double centroid_depth = (z[0] + z[1] + z[2]) / 3.0;
    return mesh_editor_screen_brush_depth_visible(
        context.depth_mask,
        distance <= 0.001 ? context.x : centroid_x,
        distance <= 0.001 ? context.y : centroid_y,
        distance <= 0.001 ? hit_depth : centroid_depth
    );
}

void mesh_editor_select_brush_faces(
    int submesh_index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection,
    const MeshEditorScreenRay* ray
) {
    if (!context.has_screen_point) {
        return;
    }
    std::set<int>& selected = selection.faces[submesh_index];
    for (std::size_t index = 0; index < submesh.faces.size(); ++index) {
        const std::array<int, 3>& face = submesh.faces[index];
        if (face[0] < 0 || face[1] < 0 || face[2] < 0
            || static_cast<std::size_t>(face[0]) >= submesh.vertices.size()
            || static_cast<std::size_t>(face[1]) >= submesh.vertices.size()
            || static_cast<std::size_t>(face[2]) >= submesh.vertices.size()) {
            continue;
        }
        bool ray_intersected = false;
        if (ray != nullptr) {
            const bool ray_visible = mesh_editor_brush_face_ray_hit(
                submesh, face, *ray, context, projection, ray_intersected
            );
            if (ray_intersected) {
                if (ray_visible) selected.insert(static_cast<int>(index));
                continue;
            }
        }
        if (mesh_editor_brush_face_screen_hit(submesh, face, context, projection)) {
            selected.insert(static_cast<int>(index));
        }
    }
    if (selected.empty()) {
        selection.faces.erase(submesh_index);
    }
}

void mesh_editor_select_brush_vertices(
    const JsonValue& item,
    int submesh_index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushSelectionContext& context
) {
    const std::map<int, double> weights = screen_brush_vertex_weights_native(
        item, submesh.vertices, nullptr, context.falloff, &context.brush, context.depth_mask
    );
    if (weights.empty()) {
        return;
    }
    std::set<int>& vertices = selection.vertices[submesh_index];
    for (const auto& weight : weights) {
        vertices.insert(weight.first);
    }
}

void mesh_editor_select_brush_submesh(
    int index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushSelectionContext& context
) {
    JsonValue item;
    item.type = JsonValue::Type::Object;
    item.object_value["index"] = mesh_editor_json_number(index);
    if (!mesh_editor_screen_brush_submesh_allowed(item, context.brush)) {
        return;
    }
    const MeshEditorScreenBrushProjection projection =
        mesh_editor_projection_for_submesh(context.projection, index);
    MeshEditorScreenRay ray;
    const bool has_ray = (context.target_mode == "edge" || context.target_mode == "face")
        && mesh_editor_screen_ray_from_projection(context.brush, projection, ray);
    if (context.target_mode == "edge") {
        mesh_editor_select_brush_edges(index, submesh, selection, context, projection, has_ray ? &ray : nullptr);
    } else if (context.target_mode == "face") {
        mesh_editor_select_brush_faces(index, submesh, selection, context, projection, has_ray ? &ray : nullptr);
    } else {
        mesh_editor_select_brush_vertices(item, index, submesh, selection, context);
    }
}

void mesh_editor_add_screen_brush_selection(
    const MeshEditorSession* session,
    const JsonValue* raw_selection,
    MeshEditorSelection& selection,
    const MeshEditorScreenBrushDepthMask* shared_depth_mask = nullptr
) {
    if (session == nullptr || raw_selection == nullptr || raw_selection->type != JsonValue::Type::Object) {
        return;
    }
    const JsonValue* raw_brush = raw_selection->get("screen_brush");
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return;
    }
    const std::string depth_mode = lower_ascii(string_or(
        raw_selection->get("selection_depth_mode"),
        string_or(raw_selection->get("depth_mode"), string_or(raw_brush->get("selection_depth_mode"), string_or(raw_brush->get("depth_mode"), "xray")))
    ));
    MeshEditorScreenBrushDepthMask depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr;
    if (depth_mode != "xray") {
        // A coalesced command replays many dabs through this function; the
        // caller rasterizes occlusion once over their union and shares it,
        // instead of every dab re-rendering every face of every submesh.
        if (shared_depth_mask != nullptr && shared_depth_mask->valid) {
            depth_mask = shared_depth_mask;
        } else {
            depth_mask_storage = mesh_editor_screen_brush_depth_mask(session, *raw_brush);
            if (depth_mask_storage.valid) depth_mask = &depth_mask_storage;
        }
    }
    MeshEditorScreenBrushSelectionContext context{
        *raw_brush,
        lower_ascii(string_or(raw_selection->get("target_mode"), string_or(raw_selection->get("selection_target"), string_or(raw_brush->get("target_mode"), "vertex")))),
        lower_ascii(string_or(raw_selection->get("falloff"), string_or(raw_brush->get("falloff"), "smooth"))),
        number_or(raw_brush->get("x"), number_or(raw_brush->get("cursor_x"), number_or(raw_brush->get("screen_x"), std::numeric_limits<double>::quiet_NaN()))),
        number_or(raw_brush->get("y"), number_or(raw_brush->get("cursor_y"), number_or(raw_brush->get("screen_y"), std::numeric_limits<double>::quiet_NaN()))),
        std::max(number_or(raw_brush->get("radius_pixels"), number_or(raw_brush->get("brush_radius_pixels"), number_or(raw_brush->get("pixels"), number_or(raw_brush->get("radius"), 0.0)))), 0.0),
        false,
        mesh_editor_screen_brush_projection(*raw_brush),
        depth_mask,
    };
    context.has_screen_point = std::isfinite(context.x) && std::isfinite(context.y) && context.radius_pixels >= 0.0;
    if (context.target_mode == "source") {
        if (bool_or(raw_selection->get("paint_sample"), false)) {
            mesh_editor_select_brush_sources(*session, selection, context);
        } else {
            mesh_editor_select_brush_source(*session, selection, context);
        }
        return;
    }
    for (const auto& entry : mesh_editor_submeshes(*session)) {
        mesh_editor_select_brush_submesh(entry.first, entry.second, selection, context);
    }
}
