void mesh_editor_collect_apply_result_indices(MeshEditorApplyState& state) {
    for (const SubmeshMeshEditResult& result : state.results) {
        if (result.index < 0) {
            continue;
        }
        state.history.topology_changed = state.history.topology_changed || result.topology_changed;
        if (!result.append_submesh) {
            state.affected_indices.insert(result.index);
            state.existing_result_indices.insert(result.index);
        }
    }
    if (!state.record_history || !state.history.topology_changed) {
        return;
    }
    state.history.selection_before = state.selection_before;
    state.history.selection_snapshot = true;
    for (const int index : state.existing_result_indices) {
        const auto before = state.pre_edit_submeshes.find(index);
        if (before == state.pre_edit_submeshes.end()) {
            throw std::runtime_error("mesh editor topology history missed an affected submesh");
        }
        state.history.before[index] = before->second;
    }
}

MeshEditorSelection mesh_editor_remap_subdivide_selection(
    const MeshEditorSelection& before,
    const std::vector<SubmeshMeshEditResult>& results
) {
    MeshEditorSelection remapped = before;
    for (const SubmeshMeshEditResult& result : results) {
        if (!result.topology_changed
            || (result.action != "subdivide" && result.action != "refine_smooth")
            || result.index < 0) {
            continue;
        }
        const int submesh_index = result.index;
        const auto selected_faces = before.faces.find(submesh_index);
        if (selected_faces != before.faces.end()) {
            remapped.faces.erase(submesh_index);
            std::set<int> mapped;
            for (std::size_t output_index = 0;
                output_index < result.topology_source_face_indices.size();
                ++output_index) {
                if (selected_faces->second.find(result.topology_source_face_indices[output_index])
                    != selected_faces->second.end()) {
                    mapped.insert(static_cast<int>(output_index));
                }
            }
            if (!mapped.empty()) remapped.faces[submesh_index] = std::move(mapped);
        }

        const auto selected_edges = before.edges.find(submesh_index);
        if (selected_edges != before.edges.end()) {
            remapped.edges.erase(submesh_index);
            std::map<std::array<int, 2>, int> midpoint_by_edge;
            for (const VertexBlend& blend : result.vertex_blends) {
                midpoint_by_edge[edge_key(blend.left, blend.right)] = blend.index;
            }
            const std::set<std::array<int, 2>> result_edges = face_edge_set(result.faces);
            std::set<std::array<int, 2>> mapped;
            for (const std::array<int, 2>& selected : selected_edges->second) {
                const std::array<int, 2> key = edge_key(selected[0], selected[1]);
                const auto midpoint = midpoint_by_edge.find(key);
                if (midpoint != midpoint_by_edge.end()) {
                    mapped.insert(edge_key(selected[0], midpoint->second));
                    mapped.insert(edge_key(midpoint->second, selected[1]));
                } else if (result_edges.find(key) != result_edges.end()) {
                    mapped.insert(key);
                }
            }
            if (!mapped.empty()) remapped.edges[submesh_index] = std::move(mapped);
        }

        const auto selected_vertices = before.vertices.find(submesh_index);
        if (selected_vertices != before.vertices.end()) {
            remapped.vertices.erase(submesh_index);
            remapped.vertex_weights.erase(submesh_index);
            std::set<int> mapped;
            for (const int vertex : selected_vertices->second) {
                if (vertex >= 0 && static_cast<std::size_t>(vertex) < result.vertices.size()) {
                    mapped.insert(vertex);
                }
            }
            for (const VertexBlend& blend : result.vertex_blends) {
                if (blend.index < 0 || static_cast<std::size_t>(blend.index) >= result.vertices.size()) {
                    continue;
                }
                // Only a midpoint whose whole parent edge was selected joins
                // the selection. Selecting every generated midpoint made each
                // Subdivide adopt the bled boundary ring too, so the split
                // region and the visible selection quadrupled per click.
                if (selected_vertices->second.find(blend.left) != selected_vertices->second.end()
                    && selected_vertices->second.find(blend.right) != selected_vertices->second.end()) {
                    mapped.insert(blend.index);
                }
            }
            if (!mapped.empty()) remapped.vertices[submesh_index] = std::move(mapped);
        }
    }
    return remapped;
}

void mesh_editor_delete_apply_parts(
    std::map<int, MeshSessionSubmesh>& native_session,
    const MeshEditorApplyState& state
) {
    if (!state.delete_parts_operation) {
        return;
    }
    for (const SubmeshMeshEditResult& result : state.results) {
        if (result.index >= 0) {
            native_session.erase(result.index);
        }
    }
}

void mesh_editor_append_apply_submeshes(
    MeshEditorSession& session,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    for (SubmeshMeshEditResult& result : state.results) {
        if (!result.append_submesh || !result.topology_changed
            || result.vertices.empty() || result.faces.empty()) {
            continue;
        }
        const int source_index = result.source_index >= 0 ? result.source_index : result.index;
        const int appended_index = mesh_editor_next_submesh_index(session);
        result.index = appended_index;
        state.affected_indices.insert(appended_index);
        state.history.absent_before.insert(appended_index);
        state.history.append_source_indices[appended_index] = source_index;
        const auto source = native_session.find(source_index);
        if (source != native_session.end() && !result.material_metadata_changed) {
            const std::string base_name = source->second.name.empty()
                ? std::string("part_") + std::to_string(source_index)
                : source->second.name;
            result.name = base_name + result.name_suffix;
            result.material = source->second.material;
            result.texture = source->second.texture;
            result.extra_attrs = source->second.extra_attrs;
            result.material_metadata_changed = true;
        }
        native_session[appended_index] = mesh_editor_submesh_from_result(result);
    }
}

void mesh_editor_apply_material_results(
    std::map<int, MeshSessionSubmesh>& native_session,
    const MeshEditorApplyState& state
) {
    for (const SubmeshMeshEditResult& result : state.results) {
        if (result.append_submesh || result.index < 0) {
            continue;
        }
        MeshSessionSubmesh updated;
        if (result.topology_changed && !result.vertices.empty()) {
            updated = mesh_editor_submesh_from_result(result);
        } else {
            const auto current = native_session.find(result.index);
            if (current == native_session.end()) {
                continue;
            }
            updated = current->second;
        }
        if (result.material_metadata_changed) {
            updated.name = result.name;
            updated.material = result.material;
            updated.texture = result.texture;
            updated.extra_attrs = result.extra_attrs;
        }
        native_session[result.index] = std::move(updated);
    }
}

void mesh_editor_attach_topology_result_metadata(
    const std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    for (SubmeshMeshEditResult& result : state.results) {
        if (!result.topology_changed || result.append_submesh || result.material_metadata_changed) {
            continue;
        }
        const auto after = native_session.find(result.index);
        if (after == native_session.end()) {
            continue;
        }
        result.name = after->second.name;
        result.material = after->second.material;
        result.texture = after->second.texture;
        result.extra_attrs = after->second.extra_attrs;
        result.material_metadata_changed = true;
    }
}

void mesh_editor_capture_sparse_apply_history(
    const std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    if (!state.record_history || state.history.topology_changed) {
        return;
    }
    for (const int index : state.existing_result_indices) {
        const auto before = state.pre_edit_channels.find(index);
        const auto after = native_session.find(index);
        if (before == state.pre_edit_channels.end() || after == native_session.end()) {
            throw std::runtime_error("mesh editor sparse history missed an affected submesh");
        }
        MeshEditorSubmeshDelta delta;
        mesh_editor_finish_pre_edit_channels(delta, before->second, after->second);
        if (state.operation == "transform" || state.operation == "brush") {
            for (const SubmeshMeshEditResult& result : state.results) {
                if (result.index == index
                    && !mesh_editor_add_sparse_position_result(delta, result, after->second)) {
                    throw std::runtime_error("mesh editor sparse position history is incomplete");
                }
            }
        }
        if (!mesh_editor_submesh_delta_empty(delta)) {
            state.history.deltas[index] = std::move(delta);
        }
    }
    if (state.history.deltas.empty()) {
        throw std::runtime_error("mesh editor sparse history captured no channel changes");
    }
}

bool mesh_editor_coalesce_apply_history(
    MeshEditorSession& session,
    MeshEditorApplyState& state
) {
    if (!state.record_history || state.history.stroke_id.empty() || session.undo_stack.empty()) {
        return false;
    }
    MeshEditorHistoryEntry& previous = session.undo_stack.back();
    if (previous.stroke_id != state.history.stroke_id
        || previous.operation != state.history.operation
        || previous.topology_changed
        || state.history.topology_changed) {
        return false;
    }
    for (const auto& item : state.history.deltas) {
        const auto found = previous.deltas.find(item.first);
        if (found != previous.deltas.end()
            && !mesh_editor_can_merge_submesh_delta(found->second, item.second)) {
            return false;
        }
    }
    for (const auto& item : state.history.deltas) {
        const auto found = previous.deltas.find(item.first);
        if (found == previous.deltas.end()) {
            previous.deltas[item.first] = item.second;
        } else {
            (void)mesh_editor_merge_submesh_delta(found->second, item.second);
        }
    }
    previous.stroke_update_count += 1;
    state.response_stroke_update_count = previous.stroke_update_count;
    mesh_editor_trim_history(session.undo_stack);
    return true;
}

void mesh_editor_publish_apply_history(
    MeshEditorSession& session,
    MeshEditorApplyState& state
) {
    if (!state.record_history) {
        return;
    }
    state.history_coalesced = mesh_editor_coalesce_apply_history(session, state);
    if (!state.history_coalesced) {
        mesh_editor_push_history(session.undo_stack, std::move(state.history));
    }
    session.redo_stack.clear();
    mesh_editor_trim_session_history(session);
}

void mesh_editor_commit_apply_results(
    MeshEditorSession& session,
    std::map<int, MeshSessionSubmesh>& native_session,
    MeshEditorApplyState& state
) {
    mesh_editor_append_refit_after_geometry(session, state);
    mesh_editor_collect_apply_result_indices(state);
    // Compose original-relative provenance against the session as it still is.
    // An admitted operation that will not compose throws from here, before the
    // first erase below, so geometry, history, and revisions stay untouched.
    mesh_editor_prepare_topology_provenance(
        native_session,
        state.results,
        state.topology_provenance_ms,
        state.topology_provenance_parent_entries
    );
    mesh_editor_delete_apply_parts(native_session, state);
    mesh_editor_append_apply_submeshes(session, native_session, state);
    if (!state.stroke_phase.empty() && session.active_stroke.active) {
        ++session.active_stroke.update_count;
        state.response_stroke_update_count = session.active_stroke.update_count;
    }
    state.applied_topology_changed = state.history.topology_changed;
    if (state.affected_indices.empty()) {
        return;
    }
    if (state.material_operation) {
        mesh_editor_apply_material_results(native_session, state);
    } else if (state.history.topology_changed) {
        mesh_editor_attach_topology_result_metadata(native_session, state);
    }
    mesh_editor_capture_sparse_apply_history(native_session, state);
    mesh_editor_finalize_morph_after_apply(session, state);
    mesh_editor_publish_apply_history(session, state);
    if (state.applied_topology_changed) {
        ++session.topology_revision;
        if (state.operation == "subdivide" || state.operation == "refine_smooth") {
            session.selection = mesh_editor_remap_subdivide_selection(state.selection_before, state.results);
        } else if (state.operation == "paste") {
            session.selection = MeshEditorSelection{};
            for (const SubmeshMeshEditResult& result : state.results) {
                if (!result.append_submesh || result.index < 0) continue;
                // Select the whole pasted layer. Face-selection values are
                // current compact offsets, so name every pasted face directly
                // rather than going through its source-face ids.
                std::set<int> pasted_faces;
                for (std::size_t face_index = 0; face_index < result.faces.size(); ++face_index) {
                    pasted_faces.insert(static_cast<int>(face_index));
                }
                session.selection.faces[result.index] = std::move(pasted_faces);
            }
        } else if (state.operation == "delete") {
            session.selection = MeshEditorSelection{};
        } else {
            session.selection = state.selection_before;
            session.selection = mesh_editor_prune_and_combine_selection(
                session,
                state.selection_before,
                "replace"
            );
        }
        ++session.selection_revision;
    }
    ++session.edit_revision;
}
