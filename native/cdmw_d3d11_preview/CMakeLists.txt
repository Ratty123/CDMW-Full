cmake_minimum_required(VERSION 3.24)
project(cdmw_d3d11_preview LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(CDMW_FETCH_DIRECTXTEX "Fetch Microsoft DirectXTex when it is not provided by DirectXTex_DIR" ON)
set(CDMW_DIRECTXTEX_COMMIT "bf256afaed1c789ddd444fb45105ffbcab283efe" CACHE STRING "Pinned DirectXTex commit")

set(BUILD_TOOLS OFF CACHE BOOL "Build DirectXTex command-line tools" FORCE)
set(BUILD_SAMPLE OFF CACHE BOOL "Build DirectXTex samples" FORCE)
set(BC_USE_OPENMP ON CACHE BOOL "Build DirectXTex BC6H/BC7 codecs with OpenMP" FORCE)
find_package(OpenMP REQUIRED COMPONENTS CXX)

find_package(DirectXTex CONFIG QUIET)
if(NOT DirectXTex_FOUND AND CDMW_FETCH_DIRECTXTEX)
    include(FetchContent)
    FetchContent_Declare(
        directxtex
        GIT_REPOSITORY https://github.com/microsoft/DirectXTex.git
        GIT_TAG ${CDMW_DIRECTXTEX_COMMIT}
        UPDATE_DISCONNECTED TRUE
    )
    FetchContent_MakeAvailable(directxtex)
endif()

set(D3D_PREVIEW_OWNER_SOURCES
    src/owners/protocol_json.cpp
    src/owners/manifest_json_slots.cpp
    src/owners/manifest_material.cpp
    src/owners/status_and_view.cpp
    src/owners/shader_sources.cpp
    src/owners/renderer_lifecycle.cpp
    src/owners/renderer_views.cpp
    src/owners/renderer_geometry_overlays.cpp
    src/owners/renderer_mesh_overlay.cpp
    src/owners/renderer_render_alignment.cpp
    src/owners/renderer_alignment_interaction.cpp
    src/owners/renderer_mesh_selection.cpp
    src/owners/renderer_mesh_updates.cpp
    src/owners/renderer_input_events.cpp
    src/owners/renderer_command_protocol.cpp
    src/owners/renderer_device_camera.cpp
    src/owners/renderer_cloth.cpp
    src/owners/renderer_resources.cpp
    src/owners/app.cpp
)

add_executable(cdmw-d3d11-preview
    src/main.cpp
    src/d3d_preview.hpp
    src/d3d_preview_internal.hpp
    src/d3d_preview_types.hpp
    src/renderer.hpp
    ${D3D_PREVIEW_OWNER_SOURCES}
)
set_source_files_properties(${D3D_PREVIEW_OWNER_SOURCES} PROPERTIES UNITY_GROUP d3d_preview_owners)
set_target_properties(cdmw-d3d11-preview PROPERTIES
    UNITY_BUILD ON
    UNITY_BUILD_MODE GROUP
    UNITY_BUILD_CODE_BEFORE_INCLUDE "#include \"d3d_preview_internal.hpp\"\nnamespace cdmw_d3d11_preview {\n"
    UNITY_BUILD_CODE_AFTER_INCLUDE "\n}  // namespace cdmw_d3d11_preview\n"
)
target_include_directories(cdmw-d3d11-preview PRIVATE src)
target_compile_definitions(cdmw-d3d11-preview PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN UNICODE _UNICODE)
target_link_libraries(cdmw-d3d11-preview PRIVATE d3d11 dxgi d3dcompiler windowscodecs OpenMP::OpenMP_CXX)

if(TARGET Microsoft::DirectXTex)
    target_link_libraries(cdmw-d3d11-preview PRIVATE Microsoft::DirectXTex)
elseif(TARGET DirectXTex)
    target_link_libraries(cdmw-d3d11-preview PRIVATE DirectXTex)
else()
    message(FATAL_ERROR "DirectXTex was not found. Set DirectXTex_DIR or enable CDMW_FETCH_DIRECTXTEX.")
endif()
