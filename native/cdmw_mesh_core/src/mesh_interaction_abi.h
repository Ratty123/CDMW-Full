#pragma once

#include <stdint.h>
#include "mesh_interaction_export.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CDMW_MESH_INTERACTION_ABI_VERSION 1u

typedef enum CdmwMeshInteractionStatus {
    CDMW_MESH_INTERACTION_OK = 0,
    CDMW_MESH_INTERACTION_INVALID_ARGUMENT = 1,
    CDMW_MESH_INTERACTION_INVALID_SIZE = 2,
    CDMW_MESH_INTERACTION_UNSUPPORTED_VERSION = 3,
    CDMW_MESH_INTERACTION_SESSION_NOT_FOUND = 4,
    CDMW_MESH_INTERACTION_SESSION_EXISTS = 5,
    CDMW_MESH_INTERACTION_REVISION_MISMATCH = 6,
    CDMW_MESH_INTERACTION_BUSY = 7,
    CDMW_MESH_INTERACTION_INVALID_STATE = 8,
    CDMW_MESH_INTERACTION_BUFFER_TOO_SMALL = 9,
    CDMW_MESH_INTERACTION_REJECTED = 10,
    CDMW_MESH_INTERACTION_INTERNAL_ERROR = 11
} CdmwMeshInteractionStatus;

typedef enum CdmwMeshInteractionStructId {
    CDMW_MESH_STRUCT_SUBMESH_V1 = 1,
    CDMW_MESH_STRUCT_SELECTION_V1 = 2,
    CDMW_MESH_STRUCT_OPEN_V1 = 3,
    CDMW_MESH_STRUCT_SESSION_V1 = 4,
    CDMW_MESH_STRUCT_SYNC_V1 = 5,
    CDMW_MESH_STRUCT_GESTURE_V1 = 6,
    CDMW_MESH_STRUCT_AUTHORITY_V1 = 7,
    CDMW_MESH_STRUCT_VERTEX_READ_V1 = 8,
    CDMW_MESH_STRUCT_DIRTY_RANGE_V1 = 9,
    CDMW_MESH_STRUCT_SELECTION_CHANGE_V1 = 10,
    CDMW_MESH_STRUCT_RESULT_V1 = 11,
    CDMW_MESH_STRUCT_PROJECTION_V1 = 12,
    CDMW_MESH_STRUCT_PREPARE_SNAPSHOT_V1 = 13
} CdmwMeshInteractionStructId;

typedef enum CdmwMeshInteractionSyncFlags {
    CDMW_MESH_SYNC_MESH = 1u << 0,
    CDMW_MESH_SYNC_SELECTION = 1u << 1,
    CDMW_MESH_SYNC_TOPOLOGY = 1u << 2,
    CDMW_MESH_SYNC_CAMERA = 1u << 3,
    CDMW_MESH_SYNC_VIEWPORT = 1u << 4
} CdmwMeshInteractionSyncFlags;

typedef enum CdmwMeshInteractionTool {
    CDMW_MESH_TOOL_SELECT = 1,
    CDMW_MESH_TOOL_MOVE = 2,
    CDMW_MESH_TOOL_GRAB = 3,
    CDMW_MESH_TOOL_SMOOTH = 4,
    CDMW_MESH_TOOL_INFLATE = 5,
    CDMW_MESH_TOOL_PINCH = 6
} CdmwMeshInteractionTool;

typedef enum CdmwMeshSelectionTarget {
    CDMW_MESH_SELECTION_VERTEX = 1,
    CDMW_MESH_SELECTION_EDGE = 2,
    CDMW_MESH_SELECTION_FACE = 3
} CdmwMeshSelectionTarget;

typedef enum CdmwMeshSelectionShape {
    CDMW_MESH_SELECTION_BRUSH = 1,
    CDMW_MESH_SELECTION_RECTANGLE = 2,
    CDMW_MESH_SELECTION_LASSO = 3
} CdmwMeshSelectionShape;

typedef enum CdmwMeshSelectionOperation {
    CDMW_MESH_SELECTION_REPLACE = 1,
    CDMW_MESH_SELECTION_ADD = 2,
    CDMW_MESH_SELECTION_SUBTRACT = 3,
    CDMW_MESH_SELECTION_TOGGLE = 4
} CdmwMeshSelectionOperation;

typedef enum CdmwMeshInteractionAuthorityAction {
    CDMW_MESH_AUTHORITY_ACCEPTED = 1,
    CDMW_MESH_AUTHORITY_REJECTED = 2,
    CDMW_MESH_AUTHORITY_UNDO = 3,
    CDMW_MESH_AUTHORITY_REDO = 4
} CdmwMeshInteractionAuthorityAction;

typedef enum CdmwMeshInteractionOperatorState {
    CDMW_MESH_OPERATOR_IDLE = 0,
    CDMW_MESH_OPERATOR_ACTIVE = 1,
    CDMW_MESH_OPERATOR_AWAITING_AUTHORITY = 2
} CdmwMeshInteractionOperatorState;

typedef struct CdmwMeshSubmeshV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    int32_t submesh_index;
    uint32_t vertex_count;
    const double* positions_xyz;
    const double* normals_xyz;
    uint32_t triangle_count;
    const uint32_t* triangle_indices;
} CdmwMeshSubmeshV1;

typedef struct CdmwMeshSelectionV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    int32_t submesh_index;
    uint32_t vertex_count;
    const uint32_t* vertex_indices;
    uint32_t face_count;
    const uint32_t* face_indices;
    uint32_t edge_count;
    const uint32_t* edge_vertex_pairs;
} CdmwMeshSelectionV1;

typedef struct CdmwMeshProjectionV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    int32_t submesh_index;
    uint32_t reserved;
    double world_view_projection[16];
} CdmwMeshProjectionV1;

typedef struct CdmwMeshInteractionOpenV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_key;
    uint64_t mesh_revision;
    uint64_t selection_revision;
    uint64_t topology_generation;
    uint64_t camera_revision;
    uint64_t viewport_revision;
    uint32_t submesh_count;
    const CdmwMeshSubmeshV1* submeshes;
} CdmwMeshInteractionOpenV1;

typedef struct CdmwMeshInteractionSessionV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_handle;
} CdmwMeshInteractionSessionV1;

typedef struct CdmwMeshInteractionSyncV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_handle;
    uint32_t flags;
    uint32_t reserved;
    uint64_t base_mesh_revision;
    uint64_t mesh_revision;
    uint64_t base_selection_revision;
    uint64_t selection_revision;
    uint64_t base_topology_generation;
    uint64_t topology_generation;
    uint64_t base_camera_revision;
    uint64_t camera_revision;
    uint64_t base_viewport_revision;
    uint64_t viewport_revision;
    uint32_t submesh_count;
    const CdmwMeshSubmeshV1* submeshes;
    uint32_t selection_count;
    const CdmwMeshSelectionV1* selections;
    uint32_t projection_count;
    const CdmwMeshProjectionV1* projections;
    double world_view_projection[16];
    double viewport_width;
    double viewport_height;
} CdmwMeshInteractionSyncV1;

typedef struct CdmwMeshInteractionGestureV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_handle;
    uint64_t gesture_id;
    uint64_t mesh_revision;
    uint64_t selection_revision;
    uint64_t topology_generation;
    uint64_t camera_revision;
    uint64_t viewport_revision;
    uint32_t tool;
    uint32_t selection_target;
    uint32_t selection_shape;
    uint32_t selection_operation;
    uint32_t xray;
    uint32_t reserved;
    double start_x;
    double start_y;
    double current_x;
    double current_y;
    double radius_pixels;
    double strength;
    double pressure;
    double delta_x;
    double delta_y;
    double delta_z;
    uint32_t point_count;
    const double* points_xy;
} CdmwMeshInteractionGestureV1;

typedef struct CdmwMeshInteractionPrepareSnapshotV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_handle;
    uint64_t mesh_revision;
    uint64_t selection_revision;
    uint64_t topology_generation;
    uint64_t camera_revision;
    uint64_t viewport_revision;
    uint64_t visible_parts_revision;
    uint64_t model_transform_revision;
    uint32_t xray;
    uint32_t reserved;
} CdmwMeshInteractionPrepareSnapshotV1;

typedef struct CdmwMeshInteractionAuthorityV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_handle;
    uint64_t gesture_id;
    uint32_t action;
    uint32_t reserved;
    uint64_t base_mesh_revision;
    uint64_t mesh_revision;
    uint64_t base_selection_revision;
    uint64_t selection_revision;
    uint64_t base_topology_generation;
    uint64_t topology_generation;
} CdmwMeshInteractionAuthorityV1;

typedef struct CdmwMeshInteractionVertexReadV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint64_t session_handle;
    int32_t submesh_index;
    uint32_t first_vertex;
    uint32_t vertex_count;
    uint32_t position_capacity;
    double* positions_xyz;
    uint32_t written_vertex_count;
} CdmwMeshInteractionVertexReadV1;

typedef struct CdmwMeshDirtyRangeV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    int32_t submesh_index;
    uint32_t first_vertex;
    uint32_t vertex_count;
    uint64_t mesh_revision;
    uint64_t topology_generation;
    uint64_t interaction_generation;
} CdmwMeshDirtyRangeV1;

typedef struct CdmwMeshSelectionChangeV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    int32_t submesh_index;
    uint32_t target;
    uint32_t first_element;
    uint32_t second_element;
    uint32_t element_count;
    uint32_t selected;
    uint64_t selection_revision;
    uint64_t interaction_generation;
} CdmwMeshSelectionChangeV1;

typedef struct CdmwMeshInteractionResultV1 {
    uint32_t struct_size;
    uint32_t struct_version;
    uint32_t status;
    uint32_t operator_state;
    uint64_t session_handle;
    uint64_t gesture_id;
    uint64_t mesh_revision;
    uint64_t selection_revision;
    uint64_t topology_generation;
    uint64_t camera_revision;
    uint64_t viewport_revision;
    uint64_t interaction_generation;
    uint32_t dirty_range_capacity;
    CdmwMeshDirtyRangeV1* dirty_ranges;
    uint32_t dirty_range_count;
    uint32_t selection_change_capacity;
    CdmwMeshSelectionChangeV1* selection_changes;
    uint32_t selection_change_count;
    char message[256];
} CdmwMeshInteractionResultV1;

CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_abi_version(void);
CDMW_MESH_INTERACTION_API const char* cdmw_mesh_interaction_abi_contract(void);
CDMW_MESH_INTERACTION_API const char* cdmw_mesh_interaction_abi_header_sha256(void);
CDMW_MESH_INTERACTION_API const char* cdmw_mesh_interaction_backend(void);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_struct_size(uint32_t struct_id);

CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_open(
    const CdmwMeshInteractionOpenV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_close(
    const CdmwMeshInteractionSessionV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_sync(
    const CdmwMeshInteractionSyncV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_prepare_snapshot_v1(
    const CdmwMeshInteractionPrepareSnapshotV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_begin(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_update(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_end(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_cancel(
    const CdmwMeshInteractionGestureV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_apply_authoritative(
    const CdmwMeshInteractionAuthorityV1* request,
    CdmwMeshInteractionResultV1* result
);
CDMW_MESH_INTERACTION_API uint32_t cdmw_mesh_interaction_read_vertices(
    CdmwMeshInteractionVertexReadV1* request,
    CdmwMeshInteractionResultV1* result
);

#ifdef __cplusplus
}
#endif
