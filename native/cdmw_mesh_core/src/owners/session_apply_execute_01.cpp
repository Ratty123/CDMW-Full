std::vector<SubmeshMeshEditResult> mesh_editor_delete_selected_parts(
    const MeshEditorSession& session,
    const std::map<int, MeshSessionSubmesh>& native_session
) {
    std::vector<SubmeshMeshEditResult> results;
    for (const int index : session.selection.source_indices) {
        const auto found = native_session.find(index);
        if (found == native_session.end()) {
            continue;
        }
        SubmeshMeshEditResult result;
        result.action = "delete";
        result.index = index;
        result.removed_vertices = static_cast<int>(found->second.vertices.size());
        result.removed_faces = static_cast<int>(found->second.faces.size());
        result.topology_changed = true;
        results.push_back(std::move(result));
    }
    return results;
}

void mesh_editor_execute_normal_operation(
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    state.edit_root.object_value["operation"] = mesh_editor_json_string(state.operation);
    std::vector<SubmeshNormalsResult> raw = run_recalculate_normals(
        mesh_editor_filter_root_to_selected_normal_targets(state.edit_root, state.operation)
    );
    for (SubmeshNormalsResult& result : raw) {
        if (!mesh_editor_normals_result_changed(result)) {
            continue;
        }
        auto found = native_session.find(result.index);
        if (found != native_session.end()) {
            MeshSessionSubmesh& updated = found->second;
            if (result.normals.size() == updated.vertices.size()) {
                updated.normals = result.normals;
            }
            if (!result.faces.empty()) {
                updated.faces = result.faces;
            }
            updated.tangents.clear();
            updated.tangent_signs.clear();
        }
        state.normal_results.push_back(std::move(result));
    }
    state.results = mesh_editor_results_from_normals_results(state.normal_results);
}

void mesh_editor_validate_auto_uv_results(const std::vector<SubmeshAutoUvResult>& results) {
    for (const SubmeshAutoUvResult& result : results) {
        if (result.status != "ok") {
            throw std::runtime_error(
                result.error.empty()
                    ? "native auto_uv failed"
                    : std::string("native auto_uv failed: ") + result.error
            );
        }
    }
}

void mesh_editor_execute_uv_operation(
    const JsonValue& edit,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    if (state.auto_uv_operation) {
        state.edit_root.object_value["operation"] = mesh_editor_json_string("auto_uv");
        state.edit_root.object_value["auto_uv"] = edit;
        std::vector<SubmeshAutoUvResult> raw = run_auto_uv(state.edit_root);
        mesh_editor_validate_auto_uv_results(raw);
        state.results = mesh_editor_results_from_auto_uv_results(
            raw, state.pre_edit_submeshes, native_session
        );
        return;
    }
    state.edit_root.object_value["operation"] = mesh_editor_json_string("uv_transform");
    state.edit_root.object_value["uv_transform"] = edit;
    std::vector<SubmeshUvTransformResult> raw = run_uv_transform(state.edit_root);
    for (SubmeshUvTransformResult& result : raw) {
        if (!mesh_editor_uv_result_changed(result)) {
            continue;
        }
        auto found = native_session.find(result.index);
        if (found != native_session.end()) {
            MeshSessionSubmesh& updated = found->second;
            if (result.clear_uvs) {
                updated.uvs.clear();
            } else if (result.uvs.size() == updated.vertices.size()) {
                updated.uvs = result.uvs;
            }
            updated.tangents.clear();
            updated.tangent_signs.clear();
        }
        state.uv_results.push_back(std::move(result));
    }
    state.results = mesh_editor_results_from_uv_results(state.uv_results);
}

void mesh_editor_execute_tangent_operation(
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    state.edit_root.object_value["operation"] = mesh_editor_json_string("generate_tangents");
    std::vector<SubmeshTangentsResult> raw = run_generate_tangents(
        mesh_editor_filter_root_to_selected_normal_targets(state.edit_root, "recalculate_normals")
    );
    for (SubmeshTangentsResult& result : raw) {
        if (!mesh_editor_tangents_result_changed(result)) {
            continue;
        }
        auto found = native_session.find(result.index);
        if (found != native_session.end()) {
            MeshSessionSubmesh& updated = found->second;
            if (result.clear_tangents) {
                updated.tangents.clear();
                updated.tangent_signs.clear();
            } else if (result.tangents.size() == updated.vertices.size()) {
                updated.tangents = result.tangents;
                updated.tangent_signs = result.tangent_signs.size() == updated.vertices.size()
                    ? result.tangent_signs
                    : std::vector<double>();
            }
        }
        state.tangent_results.push_back(std::move(result));
    }
    state.results = mesh_editor_results_from_tangents_results(state.tangent_results);
}

void mesh_editor_execute_apply_operation(
    MeshEditorSession& session,
    const JsonValue& edit,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    if (state.delete_parts_operation) {
        state.results = mesh_editor_delete_selected_parts(session, native_session);
    } else if (state.operation == "transform") {
        state.edit_root.object_value["operation"] = mesh_editor_json_string("transform");
        state.edit_root.object_value["transform"] = edit;
        state.results = mesh_editor_results_from_transform_results(run_transform(state.edit_root));
    } else if (state.normal_operation) {
        mesh_editor_execute_normal_operation(native_session, state);
    } else if (state.uv_operation) {
        mesh_editor_execute_uv_operation(edit, native_session, state);
    } else if (state.tangent_operation) {
        mesh_editor_execute_tangent_operation(native_session, state);
    } else if (state.material_operation) {
        state.results = run_mesh_editor_material_edit(session, state.edit_root, edit, state.operation);
    } else if (state.cleanup_operation) {
        state.edit_root.object_value["cleanup"] = edit;
        state.results = mesh_editor_results_from_cleanup_results(
            run_cleanup(state.edit_root), state.operation
        );
    } else {
        state.results = run_mesh_edit(state.edit_root);
    }
}
