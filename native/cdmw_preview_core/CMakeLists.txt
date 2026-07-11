cmake_minimum_required(VERSION 3.24)
project(cdmw_preview_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(PREVIEW_CORE_OWNER_SOURCES
    src/owners/protocol_json.cpp
    src/owners/archive_decode.cpp
    src/owners/archive_index.cpp
    src/owners/geometry_pac.cpp
    src/owners/geometry_static.cpp
    src/owners/material_semantics.cpp
    src/owners/material_graph.cpp
    src/owners/material_resolution.cpp
    src/owners/material_selection.cpp
    src/owners/material_archive_lookup.cpp
    src/owners/material_binding_build.cpp
    src/owners/material_bindings.cpp
    src/owners/geometry_package.cpp
    src/owners/package_material_classification.cpp
    src/owners/package_material_layers.cpp
    src/owners/package_asset_report.cpp
    src/owners/package_writer_types.cpp
    src/owners/package_writer_selection.cpp
    src/owners/package_writer_material.cpp
    src/owners/package_writer_json.cpp
    src/owners/package_writer_json_tail.cpp
    src/owners/package_writer_manifest.cpp
    src/owners/package_writer.cpp
    src/owners/preview_report.cpp
    src/owners/mesh_rebuild_pac.cpp
    src/owners/mesh_rebuild_static.cpp
    src/owners/mesh_rebuild_dispatch.cpp
    src/owners/name_index_service.cpp
    src/owners/command_dispatch.cpp
)

add_executable(cdmw-preview-core
    src/main.cpp
    src/preview_core.hpp
    src/preview_core_internal.hpp
    ${PREVIEW_CORE_OWNER_SOURCES}
)
set_source_files_properties(${PREVIEW_CORE_OWNER_SOURCES} PROPERTIES UNITY_GROUP preview_core_owners)
set_target_properties(cdmw-preview-core PROPERTIES
    UNITY_BUILD ON
    UNITY_BUILD_MODE GROUP
    UNITY_BUILD_CODE_BEFORE_INCLUDE "#include \"preview_core_internal.hpp\"\nnamespace cdmw_preview_core {\n"
    UNITY_BUILD_CODE_AFTER_INCLUDE "\n}  // namespace cdmw_preview_core\n"
)
target_compile_definitions(cdmw-preview-core PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_include_directories(cdmw-preview-core PRIVATE src)
