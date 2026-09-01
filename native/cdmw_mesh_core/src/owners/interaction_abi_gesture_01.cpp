uint32_t mesh_interaction_abi_gesture(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result,
    const std::string& phase
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    std::shared_ptr<MeshInteractionAbiSession> runtime;
    {
        std::shared_lock<std::shared_mutex> registry_lock(g_mesh_interaction_abi_registry_mutex);
        runtime = mesh_interaction_abi_find_session(request->session_handle);
    }
    if (runtime == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is not open"
        );
    }
    std::lock_guard<std::mutex> session_lock(runtime->mutex);
    if (runtime->closed) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is closed"
        );
    }
    status = mesh_interaction_abi_validate_gesture(*runtime, *request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    const bool begin = phase == "begin";
    const bool cancel = phase == "cancel";
    if (begin && runtime->operator_state != CDMW_MESH_OPERATOR_IDLE) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_BUSY, "another interaction is active");
    }
    if (!begin && (runtime->operator_state != CDMW_MESH_OPERATOR_ACTIVE
        || runtime->active_gesture_id != request->gesture_id
        || runtime->active_tool != request->tool)) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_STATE, "gesture does not match the active interaction"
        );
    }
    MeshEditorSession* editor = mesh_interaction_abi_find_editor(*runtime);
    if (editor == nullptr) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, "resident editor is missing");
    }
    if (begin) {
        runtime->active_gesture_id = request->gesture_id;
        runtime->active_tool = request->tool;
        runtime->operator_state = CDMW_MESH_OPERATOR_ACTIVE;
        runtime->baseline_selection = editor->selection;
        runtime->gesture_selection_candidates = MeshEditorSelection{};
        runtime->last_selection = runtime->baseline_selection;
        runtime->gesture_before_positions.clear();
        runtime->gesture_weights.clear();
        runtime->gesture_changed_vertices.clear();
        runtime->last_dirty_vertices.clear();
        runtime->previous_screen_x = request->current_x;
        runtime->previous_screen_y = request->current_y;
    }
    try {
        std::map<int, MeshInteractionAbiDirtySet> dirty_sets;
        if (cancel) {
            mesh_interaction_abi_force_cancel(*runtime, *editor);
            mesh_interaction_append_typed_dirty(*runtime, dirty_sets);
        } else {
            mesh_interaction_abi_apply_gesture_phase(*runtime, *editor, *request, phase);
            if (phase == "end") {
                mesh_interaction_commit_typed_history(*runtime, *editor);
            }
            mesh_interaction_append_typed_dirty(*runtime, dirty_sets);
        }
        ++runtime->interaction_generation;
        std::vector<CdmwMeshDirtyRangeV1> dirty;
        std::vector<CdmwMeshSelectionChangeV1> changes;
        const MeshEditorSelection& selection_baseline = phase == "end"
            ? runtime->baseline_selection
            : runtime->last_selection;
        mesh_interaction_abi_append_dirty_sets(dirty_sets, *runtime, dirty);
        mesh_interaction_abi_append_selection_changes(
            selection_baseline, editor->selection, *runtime, changes
        );
        runtime->last_selection = editor->selection;
        if (phase == "end") runtime->operator_state = CDMW_MESH_OPERATOR_AWAITING_AUTHORITY;
        if (cancel) {
            result->gesture_id = request->gesture_id;
            status = mesh_interaction_abi_finish_result(runtime.get(), result, dirty, changes);
            result->gesture_id = request->gesture_id;
            mesh_interaction_abi_reset_gesture(*runtime);
            return status;
        }
        return mesh_interaction_abi_finish_result(runtime.get(), result, dirty, changes);
    } catch (const std::invalid_argument& error) {
        mesh_interaction_abi_force_cancel(*runtime, *editor);
        return mesh_interaction_abi_fail(
            result,
            CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
            error.what()
        );
    } catch (const std::exception& error) {
        mesh_interaction_abi_force_cancel(*runtime, *editor);
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, error.what());
    }
}

uint32_t interaction_abi_begin(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return mesh_interaction_abi_gesture(request, result, "begin");
}

uint32_t interaction_abi_update(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return mesh_interaction_abi_gesture(request, result, "update");
}

uint32_t interaction_abi_end(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return mesh_interaction_abi_gesture(request, result, "end");
}

uint32_t interaction_abi_cancel(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return mesh_interaction_abi_gesture(request, result, "cancel");
}

uint32_t interaction_abi_apply_authoritative(
    const CdmwMeshInteractionAuthorityV1* request,
    CdmwMeshInteractionResultV1* result
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    std::shared_ptr<MeshInteractionAbiSession> runtime;
    {
        std::shared_lock<std::shared_mutex> registry_lock(g_mesh_interaction_abi_registry_mutex);
        runtime = mesh_interaction_abi_find_session(request->session_handle);
    }
    if (runtime == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is not open"
        );
    }
    std::lock_guard<std::mutex> session_lock(runtime->mutex);
    if (runtime->closed) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is closed"
        );
    }
    status = mesh_interaction_abi_validate_authority_revisions(*runtime, *request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    const bool terminal = request->action == CDMW_MESH_AUTHORITY_ACCEPTED
        || request->action == CDMW_MESH_AUTHORITY_REJECTED;
    const bool history = request->action == CDMW_MESH_AUTHORITY_UNDO
        || request->action == CDMW_MESH_AUTHORITY_REDO;
    if ((!terminal && !history)
        || (terminal && (runtime->operator_state != CDMW_MESH_OPERATOR_AWAITING_AUTHORITY
            || request->gesture_id != runtime->active_gesture_id))
        || (history && runtime->operator_state != CDMW_MESH_OPERATOR_IDLE)) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_STATE, "authority action does not match operator state"
        );
    }
    MeshEditorSession* editor = mesh_interaction_abi_find_editor(*runtime);
    if (editor == nullptr) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, "resident editor is missing");
    }
    try {
        const MeshEditorSelection before_selection = editor->selection;
        std::map<int, MeshInteractionAbiDirtySet> dirty_sets;
        if (request->action == CDMW_MESH_AUTHORITY_REJECTED) {
            if (runtime->active_tool == CDMW_MESH_TOOL_SELECT) {
                mesh_interaction_abi_rollback_stroke_history(*runtime, *editor);
                if (editor->selection.vertices != runtime->baseline_selection.vertices
                    || editor->selection.edges != runtime->baseline_selection.edges
                    || editor->selection.faces != runtime->baseline_selection.faces
                    || editor->selection.source_indices != runtime->baseline_selection.source_indices) {
                    editor->selection = runtime->baseline_selection;
                    ++editor->selection_revision;
                }
            } else {
                mesh_interaction_abi_collect_stroke_dirty(
                    *runtime, *editor, runtime->active_gesture_id, dirty_sets
                );
                mesh_interaction_abi_rollback_stroke_history(*runtime, *editor);
            }
        } else if (request->action == CDMW_MESH_AUTHORITY_UNDO) {
            if (!editor->undo_stack.empty()) {
                mesh_interaction_abi_collect_history_dirty(
                    *runtime, editor->undo_stack.back(), dirty_sets
                );
            }
            mesh_interaction_abi_apply_history(*runtime, *editor, "undo");
        } else if (request->action == CDMW_MESH_AUTHORITY_REDO) {
            if (!editor->redo_stack.empty()) {
                mesh_interaction_abi_collect_history_dirty(
                    *runtime, editor->redo_stack.back(), dirty_sets
                );
            }
            mesh_interaction_abi_apply_history(*runtime, *editor, "redo");
        }
        runtime->mesh_revision = request->mesh_revision;
        runtime->selection_revision = request->selection_revision;
        runtime->topology_generation = request->topology_generation;
        ++runtime->interaction_generation;
        std::vector<CdmwMeshDirtyRangeV1> dirty;
        std::vector<CdmwMeshSelectionChangeV1> changes;
        mesh_interaction_abi_append_dirty_sets(dirty_sets, *runtime, dirty);
        mesh_interaction_abi_append_selection_changes(
            before_selection, editor->selection, *runtime, changes
        );
        runtime->operator_state = CDMW_MESH_OPERATOR_IDLE;
        status = mesh_interaction_abi_finish_result(runtime.get(), result, dirty, changes);
        result->gesture_id = request->gesture_id;
        if (terminal) mesh_interaction_abi_reset_gesture(*runtime);
        if (request->action == CDMW_MESH_AUTHORITY_REJECTED
            && status == CDMW_MESH_INTERACTION_OK) {
            result->status = CDMW_MESH_INTERACTION_REJECTED;
            mesh_interaction_abi_write_message(result, "authoritative result rejected and resident state rolled back");
            return CDMW_MESH_INTERACTION_REJECTED;
        }
        return status;
    } catch (const std::exception& error) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, error.what());
    }
}
