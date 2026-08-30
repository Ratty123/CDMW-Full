template <typename T>
uint32_t mesh_interaction_abi_validate_request(const T* request, std::string& message) {
    if (request == nullptr) {
        message = "request is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    return mesh_interaction_abi_validate_header(
        request,
        request->struct_size,
        sizeof(T),
        request->struct_version,
        message
    );
}

uint32_t mesh_interaction_abi_prepare_call(
    const void* request,
    CdmwMeshInteractionResultV1* result,
    std::string& message
) {
    if (request == nullptr) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT, "request is null");
    }
    const uint32_t status = mesh_interaction_abi_validate_result(result, message);
    if (status != CDMW_MESH_INTERACTION_OK) {
        return mesh_interaction_abi_fail(result, status, message);
    }
    mesh_interaction_abi_clear_result(result);
    return CDMW_MESH_INTERACTION_OK;
}

uint32_t mesh_interaction_abi_validate_submesh(
    const CdmwMeshSubmeshV1& submesh,
    std::string& message
) {
    uint32_t status = mesh_interaction_abi_validate_header(
        &submesh, submesh.struct_size, sizeof(CdmwMeshSubmeshV1), submesh.struct_version, message
    );
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    if (submesh.submesh_index < 0 || submesh.vertex_count == 0 || submesh.positions_xyz == nullptr) {
        message = "submesh requires a non-negative index and vertex positions";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    if (submesh.vertex_count > static_cast<uint32_t>(INT_MAX)
        || submesh.triangle_count > static_cast<uint32_t>(INT_MAX)) {
        message = "submesh count exceeds the native index range";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    if (submesh.triangle_count > 0 && submesh.triangle_indices == nullptr) {
        message = "submesh triangle pointer is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    for (std::size_t offset = 0; offset < static_cast<std::size_t>(submesh.vertex_count) * 3; ++offset) {
        if (!std::isfinite(submesh.positions_xyz[offset])) {
            message = "submesh contains a non-finite vertex";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
        if (submesh.normals_xyz != nullptr && !std::isfinite(submesh.normals_xyz[offset])) {
            message = "submesh contains a non-finite normal";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    for (std::size_t offset = 0; offset < static_cast<std::size_t>(submesh.triangle_count) * 3; ++offset) {
        if (submesh.triangle_indices[offset] >= submesh.vertex_count) {
            message = "submesh triangle index is out of range";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    return CDMW_MESH_INTERACTION_OK;
}

JsonValue mesh_interaction_abi_submesh_json(const CdmwMeshSubmeshV1& submesh) {
    JsonValue item = mesh_interaction_abi_json_object();
    item.object_value["index"] = mesh_interaction_abi_json_number(submesh.submesh_index);
    JsonValue vertices = mesh_interaction_abi_json_array();
    std::vector<Vec3> vertex_values;
    for (uint32_t index = 0; index < submesh.vertex_count; ++index) {
        const double* value = submesh.positions_xyz + static_cast<std::size_t>(index) * 3;
        vertices.array_value.push_back(mesh_interaction_abi_vec3(value[0], value[1], value[2]));
        vertex_values.push_back({value[0], value[1], value[2]});
    }
    JsonValue faces = mesh_interaction_abi_json_array();
    std::vector<std::array<int, 3>> face_values;
    for (uint32_t index = 0; index < submesh.triangle_count; ++index) {
        const uint32_t* value = submesh.triangle_indices + static_cast<std::size_t>(index) * 3;
        faces.array_value.push_back(mesh_interaction_abi_vec3(value[0], value[1], value[2]));
        face_values.push_back({int(value[0]), int(value[1]), int(value[2])});
    }
    const std::vector<Vec3> computed_normals = submesh.normals_xyz == nullptr
        ? compute_smooth_normals(vertex_values, face_values)
        : std::vector<Vec3>{};
    JsonValue normals = mesh_interaction_abi_json_array();
    for (uint32_t index = 0; index < submesh.vertex_count; ++index) {
        const Vec3 value = submesh.normals_xyz == nullptr
            ? (index < computed_normals.size() ? computed_normals[index] : Vec3{0.0, 1.0, 0.0})
            : Vec3{
                submesh.normals_xyz[static_cast<std::size_t>(index) * 3],
                submesh.normals_xyz[static_cast<std::size_t>(index) * 3 + 1],
                submesh.normals_xyz[static_cast<std::size_t>(index) * 3 + 2]
            };
        normals.array_value.push_back(mesh_interaction_abi_vec3(value[0], value[1], value[2]));
    }
    item.object_value["vertices"] = std::move(vertices);
    item.object_value["faces"] = std::move(faces);
    item.object_value["normals"] = std::move(normals);
    return item;
}

uint32_t mesh_interaction_abi_validate_submeshes(
    uint32_t count,
    const CdmwMeshSubmeshV1* submeshes,
    std::string& message
) {
    if (count == 0 || submeshes == nullptr) {
        message = "at least one submesh is required";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    std::set<int32_t> indices;
    for (uint32_t offset = 0; offset < count; ++offset) {
        const uint32_t status = mesh_interaction_abi_validate_submesh(submeshes[offset], message);
        if (status != CDMW_MESH_INTERACTION_OK) return status;
        if (!indices.insert(submeshes[offset].submesh_index).second) {
            message = "submesh indices must be unique";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    return CDMW_MESH_INTERACTION_OK;
}

JsonValue mesh_interaction_abi_submesh_array(
    uint32_t count,
    const CdmwMeshSubmeshV1* submeshes
) {
    JsonValue result = mesh_interaction_abi_json_array();
    for (uint32_t index = 0; index < count; ++index) {
        result.array_value.push_back(mesh_interaction_abi_submesh_json(submeshes[index]));
    }
    return result;
}

uint32_t mesh_interaction_abi_validate_selection(
    const CdmwMeshSelectionV1& selection,
    std::string& message
) {
    const uint32_t status = mesh_interaction_abi_validate_header(
        &selection, selection.struct_size, sizeof(CdmwMeshSelectionV1), selection.struct_version, message
    );
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    if (selection.submesh_index < 0
        || (selection.vertex_count > 0 && selection.vertex_indices == nullptr)
        || (selection.face_count > 0 && selection.face_indices == nullptr)
        || (selection.edge_count > 0 && selection.edge_vertex_pairs == nullptr)) {
        message = "selection contains an invalid submesh or null index pointer";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    return CDMW_MESH_INTERACTION_OK;
}

JsonValue mesh_interaction_abi_index_array(uint32_t count, const uint32_t* values) {
    JsonValue result = mesh_interaction_abi_json_array();
    for (uint32_t index = 0; index < count; ++index) {
        result.array_value.push_back(mesh_interaction_abi_json_number(values[index]));
    }
    return result;
}

JsonValue mesh_interaction_abi_selection_json(
    uint32_t count,
    const CdmwMeshSelectionV1* selections
) {
    JsonValue result = mesh_interaction_abi_json_object();
    JsonValue vertices = mesh_interaction_abi_json_array();
    JsonValue faces = mesh_interaction_abi_json_array();
    JsonValue edges = mesh_interaction_abi_json_array();
    for (uint32_t index = 0; index < count; ++index) {
        const CdmwMeshSelectionV1& selection = selections[index];
        for (auto* group : {&vertices, &faces, &edges}) {
            JsonValue item = mesh_interaction_abi_json_object();
            item.object_value["index"] = mesh_interaction_abi_json_number(selection.submesh_index);
            if (group == &vertices) {
                item.object_value["vertices"] = mesh_interaction_abi_index_array(
                    selection.vertex_count, selection.vertex_indices
                );
            } else if (group == &faces) {
                item.object_value["faces"] = mesh_interaction_abi_index_array(
                    selection.face_count, selection.face_indices
                );
            } else {
                JsonValue pairs = mesh_interaction_abi_json_array();
                for (uint32_t edge = 0; edge < selection.edge_count; ++edge) {
                    const uint32_t* pair = selection.edge_vertex_pairs + static_cast<std::size_t>(edge) * 2;
                    JsonValue edge_json = mesh_interaction_abi_json_array();
                    edge_json.array_value.push_back(mesh_interaction_abi_json_number(pair[0]));
                    edge_json.array_value.push_back(mesh_interaction_abi_json_number(pair[1]));
                    pairs.array_value.push_back(std::move(edge_json));
                }
                item.object_value["edges"] = std::move(pairs);
            }
            group->array_value.push_back(std::move(item));
        }
    }
    result.object_value["vertices_by_submesh"] = std::move(vertices);
    result.object_value["faces_by_submesh"] = std::move(faces);
    result.object_value["edges_by_submesh"] = std::move(edges);
    return result;
}

uint32_t mesh_interaction_abi_validate_selections(
    uint32_t count,
    const CdmwMeshSelectionV1* selections,
    std::string& message
) {
    if (count > 0 && selections == nullptr) {
        message = "selection array pointer is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    std::set<int32_t> indices;
    for (uint32_t offset = 0; offset < count; ++offset) {
        const uint32_t status = mesh_interaction_abi_validate_selection(selections[offset], message);
        if (status != CDMW_MESH_INTERACTION_OK) return status;
        if (!indices.insert(selections[offset].submesh_index).second) {
            message = "selection submesh indices must be unique";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    return CDMW_MESH_INTERACTION_OK;
}

MeshInteractionAbiSession* mesh_interaction_abi_find_session(uint64_t handle) {
    const auto found = g_mesh_interaction_abi_sessions.find(handle);
    return found == g_mesh_interaction_abi_sessions.end() ? nullptr : &found->second;
}

MeshEditorSession* mesh_interaction_abi_find_editor(const MeshInteractionAbiSession& session) {
    const auto found = g_mesh_editor_sessions.find(session.editor_session_id);
    return found == g_mesh_editor_sessions.end() ? nullptr : &found->second;
}

bool mesh_interaction_abi_revisions_match(
    const MeshInteractionAbiSession& session,
    const CdmwMeshInteractionGestureV1& request
) {
    return request.mesh_revision == session.mesh_revision
        && request.selection_revision == session.selection_revision
        && request.topology_generation == session.topology_generation
        && request.camera_revision == session.camera_revision
        && request.viewport_revision == session.viewport_revision;
}

std::string mesh_interaction_abi_tool_name(uint32_t tool) {
    if (tool == CDMW_MESH_TOOL_GRAB) return "grab";
    if (tool == CDMW_MESH_TOOL_SMOOTH) return "smooth";
    if (tool == CDMW_MESH_TOOL_INFLATE) return "inflate";
    if (tool == CDMW_MESH_TOOL_PINCH) return "pinch";
    return "";
}

std::string mesh_interaction_abi_selection_target(uint32_t target) {
    if (target == CDMW_MESH_SELECTION_EDGE) return "edge";
    if (target == CDMW_MESH_SELECTION_FACE) return "face";
    return "vertex";
}

std::string mesh_interaction_abi_selection_operation(uint32_t operation) {
    if (operation == CDMW_MESH_SELECTION_ADD) return "add";
    if (operation == CDMW_MESH_SELECTION_SUBTRACT) return "subtract";
    if (operation == CDMW_MESH_SELECTION_TOGGLE) return "toggle";
    return "replace";
}

JsonValue mesh_interaction_abi_projection_json(const std::array<double, 16>& matrix) {
    JsonValue projection = mesh_interaction_abi_json_array();
    for (const double value : matrix) {
        projection.array_value.push_back(mesh_interaction_abi_json_number(value));
    }
    return projection;
}

void mesh_interaction_abi_add_projection(
    JsonValue& value,
    const MeshInteractionAbiSession& session
) {
    value.object_value["viewport_width"] = mesh_interaction_abi_json_number(session.viewport_width);
    value.object_value["viewport_height"] = mesh_interaction_abi_json_number(session.viewport_height);
    value.object_value["world_view_projection"] = mesh_interaction_abi_projection_json(
        session.world_view_projection
    );
    JsonValue source_indices = mesh_interaction_abi_json_array();
    JsonValue overrides = mesh_interaction_abi_json_array();
    for (const auto& item : session.submesh_world_view_projections) {
        source_indices.array_value.push_back(mesh_interaction_abi_json_number(item.first));
        JsonValue override = mesh_interaction_abi_json_object();
        override.object_value["source_submesh_index"] = mesh_interaction_abi_json_number(item.first);
        override.object_value["world_view_projection"] = mesh_interaction_abi_projection_json(
            item.second
        );
        overrides.array_value.push_back(std::move(override));
    }
    value.object_value["source_submesh_indices"] = std::move(source_indices);
    value.object_value["source_submesh_world_view_projections"] = std::move(overrides);
}

JsonValue mesh_interaction_abi_brush_json(
    const MeshInteractionAbiSession& session,
    const CdmwMeshInteractionGestureV1& request
) {
    JsonValue brush = mesh_interaction_abi_json_object();
    brush.object_value["x"] = mesh_interaction_abi_json_number(request.current_x);
    brush.object_value["y"] = mesh_interaction_abi_json_number(request.current_y);
    brush.object_value["radius_pixels"] = mesh_interaction_abi_json_number(request.radius_pixels);
    mesh_interaction_abi_add_projection(brush, session);
    return brush;
}

JsonValue mesh_interaction_abi_region_json(
    const MeshInteractionAbiSession& session,
    const CdmwMeshInteractionGestureV1& request
) {
    JsonValue region = mesh_interaction_abi_json_object();
    const char* mode = request.selection_shape == CDMW_MESH_SELECTION_LASSO ? "lasso" : "rectangle";
    region.object_value["mode"] = mesh_interaction_abi_json_string(mode);
    region.object_value["start_x"] = mesh_interaction_abi_json_number(request.start_x);
    region.object_value["start_y"] = mesh_interaction_abi_json_number(request.start_y);
    region.object_value["end_x"] = mesh_interaction_abi_json_number(request.current_x);
    region.object_value["end_y"] = mesh_interaction_abi_json_number(request.current_y);
    if (request.point_count > 0) {
        JsonValue points = mesh_interaction_abi_json_array();
        for (uint32_t index = 0; index < request.point_count; ++index) {
            const double* point = request.points_xy + static_cast<std::size_t>(index) * 2;
            JsonValue pair = mesh_interaction_abi_json_array();
            pair.array_value.push_back(mesh_interaction_abi_json_number(point[0]));
            pair.array_value.push_back(mesh_interaction_abi_json_number(point[1]));
            points.array_value.push_back(std::move(pair));
        }
        region.object_value["points"] = std::move(points);
    }
    mesh_interaction_abi_add_projection(region, session);
    return region;
}
