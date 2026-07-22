cmake_minimum_required(VERSION 3.20)
project(cdmw_mesh_core LANGUAGES C CXX)

set(MESH_CORE_OWNER_SOURCES
    src/owners/protocol_types_01.cpp
    src/owners/protocol_types_02.cpp
    src/owners/payload_selection_01.cpp
    src/owners/payload_selection_02.cpp
    src/owners/payload_selection_03.cpp
    src/owners/payload_selection_04.cpp
    src/owners/geometry_uv_01.cpp
    src/owners/geometry_uv_02.cpp
    src/owners/geometry_uv_03.cpp
    src/owners/geometry_uv_04.cpp
    src/owners/edit_topology_01.cpp
    src/owners/edit_topology_02.cpp
    src/owners/edit_topology_03.cpp
    src/owners/edit_topology_04.cpp
    src/owners/edit_topology_05.cpp
    src/owners/edit_topology_06.cpp
    src/owners/edit_topology_07.cpp
    src/owners/edit_topology_08.cpp
    src/owners/edit_topology_09.cpp
    src/owners/interchange_01.cpp
    src/owners/interchange_02.cpp
    src/owners/interchange_03.cpp
    src/owners/reports_01.cpp
    src/owners/reports_02.cpp
    src/owners/reports_03.cpp
    src/owners/reports_04.cpp
    src/owners/preview_01.cpp
    src/owners/preview_02.cpp
    src/owners/session_state_01.cpp
    src/owners/session_state_02.cpp
    src/owners/session_selection_screen_01.cpp
    src/owners/session_selection_screen_02.cpp
    src/owners/session_state_03.cpp
    src/owners/session_state_04.cpp
    src/owners/session_lifecycle_01.cpp
    src/owners/session_history_01.cpp
    src/owners/session_export_01.cpp
    src/owners/session_apply_prepare_01.cpp
    src/owners/session_morph_01.cpp
    src/owners/session_apply_execute_01.cpp
    src/owners/session_apply_commit_01.cpp
    src/owners/session_apply_01.cpp
    src/owners/session_state_05.cpp
    src/owners/session_dispatch_01.cpp
    src/owners/snapshot_report_01.cpp
    src/owners/command_protocol_01.cpp
    src/owners/service_01.cpp
)
add_executable(cdmw-mesh-core
    src/main.cpp
    src/mesh_core.hpp
    src/mesh_core_internal.hpp
    ${MESH_CORE_OWNER_SOURCES}
    third_party/mikktspace/mikktspace.c
    third_party/meshoptimizer/allocator.cpp
    third_party/meshoptimizer/indexanalyzer.cpp
    third_party/meshoptimizer/overdrawoptimizer.cpp
    third_party/meshoptimizer/rasterizer.cpp
    third_party/meshoptimizer/simplifier.cpp
    third_party/meshoptimizer/spatialorder.cpp
    third_party/meshoptimizer/vcacheoptimizer.cpp
    third_party/meshoptimizer/vfetchoptimizer.cpp
    third_party/ufbx/ufbx.c
    third_party/xatlas/xatlas.cpp
)
set_source_files_properties(${MESH_CORE_OWNER_SOURCES} PROPERTIES UNITY_GROUP mesh_core_owners)
set_target_properties(cdmw-mesh-core PROPERTIES
    UNITY_BUILD ON
    UNITY_BUILD_MODE GROUP
    UNITY_BUILD_CODE_BEFORE_INCLUDE "#include \"mesh_core_internal.hpp\"\nnamespace cdmw_mesh_core {\n"
    UNITY_BUILD_CODE_AFTER_INCLUDE "\n}  // namespace cdmw_mesh_core\n"
)
target_compile_features(cdmw-mesh-core PRIVATE cxx_std_17)
target_compile_definitions(cdmw-mesh-core PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_include_directories(cdmw-mesh-core PRIVATE src third_party/mikktspace third_party/meshoptimizer third_party/ufbx third_party/xatlas)
