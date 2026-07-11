struct MeshEditorScreenRegionSelectionContext {
    const JsonValue& region;
    std::string target_mode;
    MeshEditorScreenBrushProjection projection;
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr;
};

bool mesh_editor_screen_region_valid_face(
    const MeshSessionSubmesh& submesh,
    const std::array<int, 3>& face
) {
    return face[0] >= 0 && face[1] >= 0 && face[2] >= 0
        && static_cast<std::size_t>(face[0]) < submesh.vertices.size()
        && static_cast<std::size_t>(face[1]) < submesh.vertices.size()
        && static_cast<std::size_t>(face[2]) < submesh.vertices.size();
}

bool mesh_editor_project_screen_region_face(
    const MeshSessionSubmesh& submesh,
    const std::array<int, 3>& face,
    const MeshEditorScreenRegionSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection,
    bool need_depth,
    std::array<Vec3, 3>& projected
) {
    if (!mesh_editor_screen_region_valid_face(submesh, face)) {
        return false;
    }
    for (int corner = 0; corner < 3; ++corner) {
        Vec3& output = projected[static_cast<std::size_t>(corner)];
        if (!mesh_editor_project_screen_brush_vertex_with_projection(
                context.region,
                projection,
                submesh.vertices[static_cast<std::size_t>(face[static_cast<std::size_t>(corner)])],
                output[0],
                output[1],
                need_depth ? &output[2] : nullptr)) {
            return false;
        }
    }
    return true;
}

std::set<int> mesh_editor_screen_region_vertices(
    const MeshSessionSubmesh& submesh,
    const MeshEditorScreenRegionSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection
) {
    std::set<int> vertices;
    for (std::size_t index = 0; index < submesh.vertices.size(); ++index) {
        double x = 0.0;
        double y = 0.0;
        double depth = 0.0;
        if (!mesh_editor_project_screen_brush_vertex_with_projection(
                context.region,
                projection,
                submesh.vertices[index],
                x,
                y,
                context.depth_mask != nullptr ? &depth : nullptr)) {
            continue;
        }
        if (mesh_editor_screen_region_contains(context.region, x, y)
            && mesh_editor_screen_brush_depth_visible(context.depth_mask, x, y, depth)) {
            vertices.insert(static_cast<int>(index));
        }
    }
    return vertices;
}

bool mesh_editor_screen_region_source_hit(
    const MeshSessionSubmesh& submesh,
    const std::set<int>& vertices,
    const MeshEditorScreenRegionSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection
) {
    if (!vertices.empty()) {
        return true;
    }
    for (const std::array<int, 3>& face : submesh.faces) {
        std::array<Vec3, 3> projected{};
        if (!mesh_editor_project_screen_region_face(submesh, face, context, projection, true, projected)) {
            continue;
        }
        Vec3 sample{};
        if (mesh_editor_screen_region_triangle_intersects(
                context.region, projected[0], projected[1], projected[2], sample)
            && mesh_editor_screen_brush_depth_visible(
                context.depth_mask, sample[0], sample[1], sample[2]
            )) {
            return true;
        }
    }
    return false;
}

void mesh_editor_select_screen_region_faces(
    int submesh_index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenRegionSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection
) {
    std::set<int>& faces = selection.faces[submesh_index];
    for (std::size_t index = 0; index < submesh.faces.size(); ++index) {
        std::array<Vec3, 3> projected{};
        if (!mesh_editor_project_screen_region_face(
                submesh,
                submesh.faces[index],
                context,
                projection,
                context.depth_mask != nullptr,
                projected)) {
            continue;
        }
        Vec3 sample{};
        if (mesh_editor_screen_region_triangle_intersects(
                context.region, projected[0], projected[1], projected[2], sample)
            && mesh_editor_screen_brush_depth_visible(
                context.depth_mask, sample[0], sample[1], sample[2]
            )) {
            faces.insert(static_cast<int>(index));
        }
    }
    if (faces.empty()) {
        selection.faces.erase(submesh_index);
    }
}

bool mesh_editor_screen_region_edge_hit(
    const Vec3& start,
    const Vec3& end,
    const MeshEditorScreenRegionSelectionContext& context
) {
    Vec2 sample{};
    if (!mesh_editor_screen_region_segment_sample(
            context.region, start[0], start[1], end[0], end[1], sample)) {
        return false;
    }
    if (context.depth_mask == nullptr) {
        return true;
    }
    const double dx = end[0] - start[0];
    const double dy = end[1] - start[1];
    const double length_sq = dx * dx + dy * dy;
    const double t = length_sq <= 1.0e-12
        ? 0.0
        : std::clamp(((sample[0] - start[0]) * dx + (sample[1] - start[1]) * dy) / length_sq, 0.0, 1.0);
    return mesh_editor_screen_brush_depth_visible(
        context.depth_mask,
        sample[0],
        sample[1],
        start[2] + (end[2] - start[2]) * t
    );
}

void mesh_editor_select_screen_region_edges(
    int submesh_index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenRegionSelectionContext& context,
    const MeshEditorScreenBrushProjection& projection
) {
    std::set<std::array<int, 2>> edges;
    for (const std::array<int, 3>& face : submesh.faces) {
        const std::array<std::array<int, 2>, 3> face_edges{{
            {face[0], face[1]}, {face[1], face[2]}, {face[2], face[0]},
        }};
        for (const std::array<int, 2>& raw_edge : face_edges) {
            const std::array<int, 2> edge = edge_key(raw_edge[0], raw_edge[1]);
            if (edges.find(edge) != edges.end() || edge[0] < 0 || edge[1] < 0
                || static_cast<std::size_t>(edge[0]) >= submesh.vertices.size()
                || static_cast<std::size_t>(edge[1]) >= submesh.vertices.size()) {
                continue;
            }
            Vec3 start{};
            Vec3 end{};
            if (!mesh_editor_project_screen_brush_vertex_with_projection(
                    context.region,
                    projection,
                    submesh.vertices[static_cast<std::size_t>(edge[0])],
                    start[0],
                    start[1],
                    context.depth_mask != nullptr ? &start[2] : nullptr)
                || !mesh_editor_project_screen_brush_vertex_with_projection(
                    context.region,
                    projection,
                    submesh.vertices[static_cast<std::size_t>(edge[1])],
                    end[0],
                    end[1],
                    context.depth_mask != nullptr ? &end[2] : nullptr)) {
                continue;
            }
            if (mesh_editor_screen_region_edge_hit(start, end, context)) {
                edges.insert(edge);
            }
        }
    }
    if (!edges.empty()) {
        selection.edges[submesh_index] = std::move(edges);
    }
}

void mesh_editor_select_screen_region_submesh(
    int index,
    const MeshSessionSubmesh& submesh,
    MeshEditorSelection& selection,
    const MeshEditorScreenRegionSelectionContext& context
) {
    JsonValue item;
    item.type = JsonValue::Type::Object;
    item.object_value["index"] = mesh_editor_json_number(index);
    if (!mesh_editor_screen_brush_submesh_allowed(item, context.region)) {
        return;
    }
    const MeshEditorScreenBrushProjection projection =
        mesh_editor_projection_for_submesh(context.projection, index);
    std::set<int> vertices = mesh_editor_screen_region_vertices(submesh, context, projection);
    if (context.target_mode == "source") {
        if (mesh_editor_screen_region_source_hit(submesh, vertices, context, projection)) {
            selection.source_indices.insert(index);
        }
    } else if (context.target_mode == "face") {
        mesh_editor_select_screen_region_faces(index, submesh, selection, context, projection);
    } else if (context.target_mode == "edge") {
        mesh_editor_select_screen_region_edges(index, submesh, selection, context, projection);
    } else if (!vertices.empty()) {
        selection.vertices[index] = std::move(vertices);
    }
}

void mesh_editor_add_screen_region_selection(
    const MeshEditorSession* session,
    const JsonValue* raw_selection,
    MeshEditorSelection& selection
) {
    if (session == nullptr || raw_selection == nullptr || raw_selection->type != JsonValue::Type::Object) {
        return;
    }
    const JsonValue* raw_region = raw_selection->get("screen_region");
    if (raw_region == nullptr || raw_region->type != JsonValue::Type::Object) {
        return;
    }
    const std::string depth_mode = lower_ascii(string_or(
        raw_selection->get("selection_depth_mode"),
        string_or(raw_selection->get("depth_mode"), string_or(raw_region->get("selection_depth_mode"), string_or(raw_region->get("depth_mode"), "xray")))
    ));
    MeshEditorScreenBrushDepthMask depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr;
    if (depth_mode != "xray") {
        depth_mask_storage = mesh_editor_screen_brush_depth_mask(session, *raw_region);
        if (depth_mask_storage.valid) depth_mask = &depth_mask_storage;
    }
    const MeshEditorScreenRegionSelectionContext context{
        *raw_region,
        lower_ascii(string_or(raw_selection->get("target_mode"), string_or(raw_selection->get("selection_target"), string_or(raw_region->get("target_mode"), "vertex")))),
        mesh_editor_screen_brush_projection(*raw_region),
        depth_mask,
    };
    for (const auto& entry : mesh_editor_submeshes(*session)) {
        mesh_editor_select_screen_region_submesh(entry.first, entry.second, selection, context);
    }
}
