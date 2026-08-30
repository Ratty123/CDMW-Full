uint32_t interaction_abi_open(
    const CdmwMeshInteractionOpenV1* request,
    CdmwMeshInteractionResultV1* result
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    if (request->session_key == 0) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT, "session_key must be non-zero"
        );
    }
    status = mesh_interaction_abi_validate_submeshes(
        request->submesh_count, request->submeshes, message
    );
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    std::lock_guard<std::mutex> lock(g_mesh_interaction_abi_mutex);
    if (g_mesh_interaction_abi_session_keys.find(request->session_key)
        != g_mesh_interaction_abi_session_keys.end()) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_EXISTS, "session_key is already open"
        );
    }
    const uint64_t handle = g_mesh_interaction_abi_next_handle++;
    const std::string editor_id = "abi-" + std::to_string(request->session_key)
        + "-" + std::to_string(handle);
    try {
        JsonValue root = mesh_interaction_abi_json_object();
        root.object_value["command"] = mesh_interaction_abi_json_string("open");
        root.object_value["session_id"] = mesh_interaction_abi_json_string(editor_id);
        root.object_value["submeshes"] = mesh_interaction_abi_submesh_array(
            request->submesh_count, request->submeshes
        );
        (void)mesh_editor_open_session_report(
            root, editor_id, mesh_editor_native_session_id(editor_id), std::chrono::steady_clock::now()
        );
        MeshInteractionAbiSession runtime;
        runtime.handle = handle;
        runtime.session_key = request->session_key;
        runtime.editor_session_id = editor_id;
        runtime.mesh_revision = request->mesh_revision;
        runtime.selection_revision = request->selection_revision;
        runtime.topology_generation = request->topology_generation;
        runtime.camera_revision = request->camera_revision;
        runtime.viewport_revision = request->viewport_revision;
        g_mesh_interaction_abi_sessions[handle] = std::move(runtime);
        g_mesh_interaction_abi_session_keys[request->session_key] = handle;
        MeshInteractionAbiSession& inserted = g_mesh_interaction_abi_sessions[handle];
        MeshEditorSession* editor = mesh_interaction_abi_find_editor(inserted);
        std::map<int, MeshInteractionAbiDirtySet> dirty_sets;
        std::vector<CdmwMeshDirtyRangeV1> dirty;
        if (editor != nullptr) {
            ++inserted.interaction_generation;
            mesh_interaction_abi_collect_full_dirty(*editor, dirty_sets);
            mesh_interaction_abi_append_dirty_sets(dirty_sets, inserted, dirty);
        }
        return mesh_interaction_abi_finish_result(inserted.handle ? &inserted : nullptr, result, dirty, {});
    } catch (const std::exception& error) {
        g_mesh_editor_sessions.erase(editor_id);
        g_mesh_sessions.erase(mesh_editor_native_session_id(editor_id));
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, error.what());
    }
}

uint32_t interaction_abi_close(
    const CdmwMeshInteractionSessionV1* request,
    CdmwMeshInteractionResultV1* result
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    std::lock_guard<std::mutex> lock(g_mesh_interaction_abi_mutex);
    MeshInteractionAbiSession* runtime = mesh_interaction_abi_find_session(request->session_handle);
    if (runtime == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is not open"
        );
    }
    try {
        MeshEditorSession* editor = mesh_interaction_abi_find_editor(*runtime);
        if (editor != nullptr && runtime->operator_state != CDMW_MESH_OPERATOR_IDLE) {
            mesh_interaction_abi_force_cancel(*runtime, *editor);
        }
        const uint64_t handle = runtime->handle;
        const uint64_t key = runtime->session_key;
        const std::string editor_id = runtime->editor_session_id;
        runtime->operator_state = CDMW_MESH_OPERATOR_IDLE;
        status = mesh_interaction_abi_finish_result(runtime, result, {}, {});
        (void)mesh_editor_close_session_report(
            editor_id, mesh_editor_native_session_id(editor_id), std::chrono::steady_clock::now()
        );
        g_mesh_interaction_abi_sessions.erase(handle);
        g_mesh_interaction_abi_session_keys.erase(key);
        return status;
    } catch (const std::exception& error) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, error.what());
    }
}

uint32_t interaction_abi_sync(
    const CdmwMeshInteractionSyncV1* request,
    CdmwMeshInteractionResultV1* result
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    if (request->flags == 0 || (request->flags & ~31u) != 0) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT, "sync flags are empty or unsupported"
        );
    }
    if ((request->flags & CDMW_MESH_SYNC_MESH) != 0) {
        status = mesh_interaction_abi_validate_submeshes(
            request->submesh_count, request->submeshes, message
        );
        if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    }
    if ((request->flags & CDMW_MESH_SYNC_SELECTION) != 0) {
        status = mesh_interaction_abi_validate_selections(
            request->selection_count, request->selections, message
        );
        if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    }
    if ((request->flags & CDMW_MESH_SYNC_CAMERA) != 0) {
        if (request->projection_count > 0 && request->projections == nullptr) {
            return mesh_interaction_abi_fail(
                result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
                "camera projection array pointer is null"
            );
        }
        for (const double value : request->world_view_projection) {
            if (!std::isfinite(value)) {
                return mesh_interaction_abi_fail(
                    result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
                    "camera matrix contains a non-finite value"
                );
            }
        }
        std::set<int> projection_indices;
        for (uint32_t index = 0; index < request->projection_count; ++index) {
            const CdmwMeshProjectionV1& projection = request->projections[index];
            status = mesh_interaction_abi_validate_header(
                &projection,
                projection.struct_size,
                sizeof(CdmwMeshProjectionV1),
                projection.struct_version,
                message
            );
            if (status != CDMW_MESH_INTERACTION_OK) {
                return mesh_interaction_abi_fail(result, status, message);
            }
            if (projection.submesh_index < 0
                || !projection_indices.insert(projection.submesh_index).second) {
                return mesh_interaction_abi_fail(
                    result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
                    "camera projections contain an invalid or duplicate submesh"
                );
            }
            for (const double value : projection.world_view_projection) {
                if (!std::isfinite(value)) {
                    return mesh_interaction_abi_fail(
                        result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
                        "submesh camera projection contains a non-finite value"
                    );
                }
            }
        }
    }
    if ((request->flags & CDMW_MESH_SYNC_VIEWPORT) != 0
        && (!std::isfinite(request->viewport_width) || !std::isfinite(request->viewport_height)
            || request->viewport_width <= 0.0 || request->viewport_height <= 0.0)) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
            "viewport dimensions must be finite and positive"
        );
    }
    std::lock_guard<std::mutex> lock(g_mesh_interaction_abi_mutex);
    MeshInteractionAbiSession* runtime = mesh_interaction_abi_find_session(request->session_handle);
    if (runtime == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is not open"
        );
    }
    if (runtime->operator_state != CDMW_MESH_OPERATOR_IDLE) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_BUSY, "session has an active interaction");
    }
    status = mesh_interaction_abi_validate_sync_revisions(*runtime, *request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    MeshEditorSession* editor = mesh_interaction_abi_find_editor(*runtime);
    if (editor == nullptr) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, "resident editor is missing");
    }
    try {
        const MeshEditorSelection before_selection = editor->selection;
        if ((request->flags & CDMW_MESH_SYNC_MESH) != 0) {
            mesh_interaction_abi_replace_mesh(*runtime, *editor, *request);
        }
        if ((request->flags & CDMW_MESH_SYNC_SELECTION) != 0) {
            mesh_interaction_abi_replace_selection(*runtime, *editor, *request);
        }
        if ((request->flags & CDMW_MESH_SYNC_TOPOLOGY) != 0) {
            runtime->topology_generation = request->topology_generation;
        }
        if ((request->flags & CDMW_MESH_SYNC_CAMERA) != 0) {
            std::copy(std::begin(request->world_view_projection), std::end(request->world_view_projection), runtime->world_view_projection.begin());
            runtime->submesh_world_view_projections.clear();
            for (uint32_t index = 0; index < request->projection_count; ++index) {
                const CdmwMeshProjectionV1& projection = request->projections[index];
                std::array<double, 16>& matrix =
                    runtime->submesh_world_view_projections[projection.submesh_index];
                std::copy(
                    std::begin(projection.world_view_projection),
                    std::end(projection.world_view_projection),
                    matrix.begin()
                );
            }
            runtime->camera_valid = true;
            runtime->camera_revision = request->camera_revision;
        }
        if ((request->flags & CDMW_MESH_SYNC_VIEWPORT) != 0) {
            runtime->viewport_width = request->viewport_width;
            runtime->viewport_height = request->viewport_height;
            runtime->viewport_revision = request->viewport_revision;
        }
        ++runtime->interaction_generation;
        std::map<int, MeshInteractionAbiDirtySet> dirty_sets;
        std::vector<CdmwMeshDirtyRangeV1> dirty;
        std::vector<CdmwMeshSelectionChangeV1> changes;
        if ((request->flags & CDMW_MESH_SYNC_MESH) != 0) {
            mesh_interaction_abi_collect_full_dirty(*editor, dirty_sets);
            mesh_interaction_abi_append_dirty_sets(dirty_sets, *runtime, dirty);
        }
        mesh_interaction_abi_append_selection_changes(
            before_selection, editor->selection, *runtime, changes
        );
        return mesh_interaction_abi_finish_result(runtime, result, dirty, changes);
    } catch (const std::exception& error) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT, error.what());
    }
}
