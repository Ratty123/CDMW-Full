uint32_t interaction_abi_read_vertices(
    CdmwMeshInteractionVertexReadV1* request,
    CdmwMeshInteractionResultV1* result
) {
    std::string message;
    uint32_t status = mesh_interaction_abi_prepare_call(request, result, message);
    if (status != CDMW_MESH_INTERACTION_OK) return status;
    status = mesh_interaction_abi_validate_request(request, message);
    if (status != CDMW_MESH_INTERACTION_OK) return mesh_interaction_abi_fail(result, status, message);
    request->written_vertex_count = 0;
    if (request->submesh_index < 0 || request->vertex_count == 0 || request->positions_xyz == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT,
            "vertex read requires a submesh, non-zero count, and output pointer"
        );
    }
    const uint64_t required_position_count = static_cast<uint64_t>(request->vertex_count) * 3u;
    if (required_position_count > UINT32_MAX
        || request->position_capacity < required_position_count) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_BUFFER_TOO_SMALL,
            "vertex read position_capacity is measured in doubles and is too small"
        );
    }
    std::lock_guard<std::mutex> lock(g_mesh_interaction_abi_mutex);
    MeshInteractionAbiSession* runtime = mesh_interaction_abi_find_session(request->session_handle);
    if (runtime == nullptr) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_SESSION_NOT_FOUND, "session handle is not open"
        );
    }
    MeshEditorSession* editor = mesh_interaction_abi_find_editor(*runtime);
    if (editor == nullptr) {
        return mesh_interaction_abi_fail(result, CDMW_MESH_INTERACTION_INTERNAL_ERROR, "resident editor is missing");
    }
    const auto& submeshes = mesh_editor_submeshes(*editor);
    const auto found = submeshes.find(request->submesh_index);
    if (found == submeshes.end()
        || request->first_vertex > found->second.vertices.size()
        || request->vertex_count > found->second.vertices.size() - request->first_vertex) {
        return mesh_interaction_abi_fail(
            result, CDMW_MESH_INTERACTION_INVALID_ARGUMENT, "vertex read range is out of bounds"
        );
    }
    for (uint32_t index = 0; index < request->vertex_count; ++index) {
        const Vec3& value = found->second.vertices[request->first_vertex + index];
        double* destination = request->positions_xyz + static_cast<std::size_t>(index) * 3;
        destination[0] = value[0];
        destination[1] = value[1];
        destination[2] = value[2];
    }
    request->written_vertex_count = request->vertex_count;
    return mesh_interaction_abi_finish_result(runtime, result, {}, {});
}
