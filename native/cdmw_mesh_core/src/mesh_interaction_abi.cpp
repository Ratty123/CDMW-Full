#include "mesh_core.hpp"

#ifndef CDMW_MESH_INTERACTION_ABI_HEADER_SHA256
#define CDMW_MESH_INTERACTION_ABI_HEADER_SHA256 "unconfigured"
#endif

extern "C" {

uint32_t cdmw_mesh_interaction_abi_version(void) {
    return CDMW_MESH_INTERACTION_ABI_VERSION;
}

const char* cdmw_mesh_interaction_abi_contract(void) {
    return "cdmw_mesh_interaction_abi_v1";
}

const char* cdmw_mesh_interaction_abi_header_sha256(void) {
    return CDMW_MESH_INTERACTION_ABI_HEADER_SHA256;
}

const char* cdmw_mesh_interaction_backend(void) {
    return "cdmw_mesh_core_0.1";
}

uint32_t cdmw_mesh_interaction_struct_size(uint32_t struct_id) {
    switch (struct_id) {
    case CDMW_MESH_STRUCT_SUBMESH_V1: return sizeof(CdmwMeshSubmeshV1);
    case CDMW_MESH_STRUCT_SELECTION_V1: return sizeof(CdmwMeshSelectionV1);
    case CDMW_MESH_STRUCT_OPEN_V1: return sizeof(CdmwMeshInteractionOpenV1);
    case CDMW_MESH_STRUCT_SESSION_V1: return sizeof(CdmwMeshInteractionSessionV1);
    case CDMW_MESH_STRUCT_SYNC_V1: return sizeof(CdmwMeshInteractionSyncV1);
    case CDMW_MESH_STRUCT_GESTURE_V1: return sizeof(CdmwMeshInteractionGestureV1);
    case CDMW_MESH_STRUCT_AUTHORITY_V1: return sizeof(CdmwMeshInteractionAuthorityV1);
    case CDMW_MESH_STRUCT_VERTEX_READ_V1: return sizeof(CdmwMeshInteractionVertexReadV1);
    case CDMW_MESH_STRUCT_DIRTY_RANGE_V1: return sizeof(CdmwMeshDirtyRangeV1);
    case CDMW_MESH_STRUCT_SELECTION_CHANGE_V1: return sizeof(CdmwMeshSelectionChangeV1);
    case CDMW_MESH_STRUCT_RESULT_V1: return sizeof(CdmwMeshInteractionResultV1);
    case CDMW_MESH_STRUCT_PROJECTION_V1: return sizeof(CdmwMeshProjectionV1);
    case CDMW_MESH_STRUCT_PREPARE_SNAPSHOT_V1: return sizeof(CdmwMeshInteractionPrepareSnapshotV1);
    default: return 0;
    }
}

uint32_t cdmw_mesh_interaction_open(
    const CdmwMeshInteractionOpenV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_open(request, result);
}

uint32_t cdmw_mesh_interaction_close(
    const CdmwMeshInteractionSessionV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_close(request, result);
}

uint32_t cdmw_mesh_interaction_sync(
    const CdmwMeshInteractionSyncV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_sync(request, result);
}

uint32_t cdmw_mesh_interaction_prepare_snapshot_v1(
    const CdmwMeshInteractionPrepareSnapshotV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_prepare_snapshot(request, result);
}

uint32_t cdmw_mesh_interaction_begin(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_begin(request, result);
}

uint32_t cdmw_mesh_interaction_update(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_update(request, result);
}

uint32_t cdmw_mesh_interaction_end(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_end(request, result);
}

uint32_t cdmw_mesh_interaction_cancel(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_cancel(request, result);
}

uint32_t cdmw_mesh_interaction_apply_authoritative(
    const CdmwMeshInteractionAuthorityV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_apply_authoritative(request, result);
}

uint32_t cdmw_mesh_interaction_read_vertices(
    CdmwMeshInteractionVertexReadV1* request,
    CdmwMeshInteractionResultV1* result
) {
    return cdmw_mesh_core::interaction_abi_read_vertices(request, result);
}

}  // extern "C"
