#pragma once

#include <string>

#include "mesh_interaction_abi.h"

namespace cdmw_mesh_core {

int mesh_core_json_command(
    const std::string& command,
    const std::string& job_path,
    const std::string& report_path
);
int run_service();

uint32_t interaction_abi_open(
    const CdmwMeshInteractionOpenV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_close(
    const CdmwMeshInteractionSessionV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_sync(
    const CdmwMeshInteractionSyncV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_begin(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_update(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_end(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_cancel(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_apply_authoritative(
    const CdmwMeshInteractionAuthorityV1* request,
    CdmwMeshInteractionResultV1* result
);
uint32_t interaction_abi_read_vertices(
    CdmwMeshInteractionVertexReadV1* request,
    CdmwMeshInteractionResultV1* result
);

}  // namespace cdmw_mesh_core
