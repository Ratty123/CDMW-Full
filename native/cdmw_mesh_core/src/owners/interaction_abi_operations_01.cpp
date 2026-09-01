uint32_t mesh_interaction_abi_validate_gesture(
    const MeshInteractionAbiSession& session,
    const CdmwMeshInteractionGestureV1& request,
    std::string& message
) {
    if (request.gesture_id == 0 || request.tool < CDMW_MESH_TOOL_SELECT || request.tool > CDMW_MESH_TOOL_PINCH) {
        message = "gesture requires a non-zero id and supported tool";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    if (!mesh_interaction_abi_revisions_match(session, request)) {
        message = "gesture revisions do not match the resident session";
        return CDMW_MESH_INTERACTION_REVISION_MISMATCH;
    }
    if (!mesh_interaction_snapshot_matches(session, request)) {
        message = "indexed interaction snapshot is not prepared for these revisions";
        return CDMW_MESH_INTERACTION_INVALID_STATE;
    }
    const double values[] = {
        request.start_x, request.start_y, request.current_x, request.current_y,
        request.radius_pixels, request.strength, request.pressure,
        request.delta_x, request.delta_y, request.delta_z
    };
    for (const double value : values) {
        if (!std::isfinite(value)) {
            message = "gesture contains a non-finite value";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    if (request.point_count > 0 && request.points_xy == nullptr) {
        message = "gesture point pointer is null";
        return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
    }
    for (std::size_t offset = 0; offset < static_cast<std::size_t>(request.point_count) * 2; ++offset) {
        if (!std::isfinite(request.points_xy[offset])) {
            message = "gesture contains a non-finite selection point";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    if (request.tool == CDMW_MESH_TOOL_SELECT) {
        if (request.selection_target < CDMW_MESH_SELECTION_VERTEX
            || request.selection_target > CDMW_MESH_SELECTION_FACE
            || request.selection_shape < CDMW_MESH_SELECTION_BRUSH
            || request.selection_shape > CDMW_MESH_SELECTION_LASSO
            || request.selection_operation < CDMW_MESH_SELECTION_REPLACE
            || request.selection_operation > CDMW_MESH_SELECTION_TOGGLE) {
            message = "selection gesture mode is invalid";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
        if (request.selection_shape == CDMW_MESH_SELECTION_LASSO && request.point_count < 3) {
            message = "lasso selection requires at least three points";
            return CDMW_MESH_INTERACTION_INVALID_ARGUMENT;
        }
    }
    if ((request.tool != CDMW_MESH_TOOL_MOVE || request.tool == CDMW_MESH_TOOL_SELECT)
        && (!session.camera_valid || session.viewport_width <= 0.0 || session.viewport_height <= 0.0)) {
        message = "screen interaction requires synchronized camera and viewport state";
        return CDMW_MESH_INTERACTION_INVALID_STATE;
    }
    return CDMW_MESH_INTERACTION_OK;
}

void mesh_interaction_abi_apply_selection_phase(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const CdmwMeshInteractionGestureV1& request
) {
    const MeshEditorSelection candidates = mesh_interaction_typed_selection_candidates(
        runtime.snapshot, request
    );
    std::shared_lock<std::shared_mutex> editor_lifetime_lock(
        g_mesh_interaction_abi_editor_registry_mutex
    );
    if (request.selection_shape == CDMW_MESH_SELECTION_BRUSH) {
        editor.selection = runtime.gesture_selection_candidates;
        runtime.gesture_selection_candidates = mesh_editor_prune_and_combine_selection(
            editor, candidates, "add"
        );
    } else {
        runtime.gesture_selection_candidates = candidates;
    }
    editor.selection = runtime.baseline_selection;
    editor.selection = mesh_editor_prune_and_combine_selection(
        editor,
        runtime.gesture_selection_candidates,
        mesh_interaction_abi_selection_operation(request.selection_operation)
    );
    ++editor.selection_revision;
}

void mesh_interaction_abi_apply_gesture_phase(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const CdmwMeshInteractionGestureV1& request,
    const std::string& phase
) {
    if (request.tool == CDMW_MESH_TOOL_SELECT) {
        if (phase != "end") {
            mesh_interaction_abi_apply_selection_phase(runtime, editor, request);
        }
        return;
    }
    mesh_interaction_apply_typed_deformation(runtime, editor, request, phase);
}

void mesh_interaction_abi_apply_history(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const std::string& command
);

void mesh_interaction_abi_rollback_stroke_history(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor
) {
    const std::string stroke_id = std::to_string(runtime.active_gesture_id);
    while (!editor.undo_stack.empty() && editor.undo_stack.back().stroke_id == stroke_id) {
        mesh_interaction_abi_apply_history(runtime, editor, "undo");
    }
    editor.redo_stack.clear();
}

void mesh_interaction_abi_force_cancel(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor
) {
    mesh_interaction_cancel_typed_gesture(runtime, editor);
    runtime.operator_state = CDMW_MESH_OPERATOR_IDLE;
    runtime.active_gesture_id = 0;
    runtime.active_tool = 0;
}

void mesh_interaction_abi_reset_gesture(MeshInteractionAbiSession& runtime) {
    runtime.operator_state = CDMW_MESH_OPERATOR_IDLE;
    runtime.active_gesture_id = 0;
    runtime.active_tool = 0;
    runtime.baseline_selection = MeshEditorSelection{};
    runtime.gesture_selection_candidates = MeshEditorSelection{};
    runtime.last_selection = MeshEditorSelection{};
    runtime.gesture_before_positions.clear();
    runtime.gesture_weights.clear();
    runtime.gesture_changed_vertices.clear();
    runtime.last_dirty_vertices.clear();
    runtime.previous_screen_x = 0.0;
    runtime.previous_screen_y = 0.0;
}

uint32_t mesh_interaction_abi_validate_sync_revisions(
    const MeshInteractionAbiSession& session,
    const CdmwMeshInteractionSyncV1& request,
    std::string& message
) {
    struct RevisionItem { uint32_t flag; uint64_t current; uint64_t base; uint64_t next; };
    const RevisionItem revisions[] = {
        {CDMW_MESH_SYNC_MESH, session.mesh_revision, request.base_mesh_revision, request.mesh_revision},
        {CDMW_MESH_SYNC_SELECTION, session.selection_revision, request.base_selection_revision, request.selection_revision},
        {CDMW_MESH_SYNC_TOPOLOGY, session.topology_generation, request.base_topology_generation, request.topology_generation},
        {CDMW_MESH_SYNC_CAMERA, session.camera_revision, request.base_camera_revision, request.camera_revision},
        {CDMW_MESH_SYNC_VIEWPORT, session.viewport_revision, request.base_viewport_revision, request.viewport_revision},
    };
    for (const RevisionItem& revision : revisions) {
        if ((request.flags & revision.flag) == 0) continue;
        if (revision.base != revision.current || revision.next < revision.base) {
            message = "synchronization revision is stale or regresses";
            return CDMW_MESH_INTERACTION_REVISION_MISMATCH;
        }
    }
    return CDMW_MESH_INTERACTION_OK;
}

void mesh_interaction_abi_replace_mesh(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const CdmwMeshInteractionSyncV1& request
) {
    std::map<int, MeshSessionSubmesh> replacements;
    for (uint32_t index = 0; index < request.submesh_count; ++index) {
        JsonValue item = mesh_interaction_abi_submesh_json(request.submeshes[index]);
        MeshSessionSubmesh submesh = mesh_session_submesh_from_item(item);
        mesh_editor_initialize_identity_topology_provenance(submesh);
        replacements[request.submeshes[index].submesh_index] = std::move(submesh);
    }
    auto* submeshes = mesh_interaction_abi_find_submeshes(runtime);
    if (submeshes == nullptr) throw std::runtime_error("resident mesh session is missing");
    *submeshes = std::move(replacements);
    editor.undo_stack.clear();
    editor.redo_stack.clear();
    editor.active_stroke = MeshEditorStroke{};
    runtime.mesh_revision = request.mesh_revision;
}

void mesh_interaction_abi_replace_selection(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const CdmwMeshInteractionSyncV1& request
) {
    JsonValue selection = mesh_interaction_abi_selection_json(
        request.selection_count, request.selections
    );
    const MeshEditorSelection parsed = mesh_editor_selection_from_json(&selection, &editor);
    std::shared_lock<std::shared_mutex> editor_lifetime_lock(
        g_mesh_interaction_abi_editor_registry_mutex
    );
    editor.selection = mesh_editor_prune_and_combine_selection(editor, parsed, "replace");
    ++editor.selection_revision;
    runtime.selection_revision = request.selection_revision;
}

uint32_t mesh_interaction_abi_validate_authority_revisions(
    const MeshInteractionAbiSession& session,
    const CdmwMeshInteractionAuthorityV1& request,
    std::string& message
) {
    if (request.base_mesh_revision != session.mesh_revision
        || request.base_selection_revision != session.selection_revision
        || request.base_topology_generation != session.topology_generation
        || request.mesh_revision < request.base_mesh_revision
        || request.selection_revision < request.base_selection_revision
        || request.topology_generation < request.base_topology_generation) {
        message = "authoritative result revisions are stale or regress";
        return CDMW_MESH_INTERACTION_REVISION_MISMATCH;
    }
    return CDMW_MESH_INTERACTION_OK;
}

void mesh_interaction_abi_apply_history(
    MeshInteractionAbiSession& runtime,
    MeshEditorSession& editor,
    const std::string& command
) {
    JsonValue root = mesh_interaction_abi_json_object();
    root.object_value["command"] = mesh_interaction_abi_json_string(command);
    root.object_value["session_id"] = mesh_interaction_abi_json_string(runtime.editor_session_id);
    root.object_value["include_edit_report"] = mesh_interaction_abi_json_bool(false);
    std::shared_lock<std::shared_mutex> editor_lifetime_lock(
        g_mesh_interaction_abi_editor_registry_mutex
    );
    (void)mesh_editor_history_session_report(
        command, root, runtime.editor_session_id, editor, std::chrono::steady_clock::now()
    );
}
