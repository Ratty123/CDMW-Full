cmake_minimum_required(VERSION 3.24)
project(cd_texture_dx LANGUAGES CXX)

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

set(TEXTURE_DX_OWNER_SOURCES
    src/common.cpp
    src/preview.cpp
    src/encode.cpp
    src/self_test.cpp
    src/texture_tool.h
    src/texture_tool_internal.h
)

add_executable(cd-texture-dx src/main.cpp ${TEXTURE_DX_OWNER_SOURCES})
target_compile_definitions(cd-texture-dx PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_link_libraries(cd-texture-dx PRIVATE windowscodecs OpenMP::OpenMP_CXX)

if(TARGET Microsoft::DirectXTex)
    target_link_libraries(cd-texture-dx PRIVATE Microsoft::DirectXTex)
elseif(TARGET DirectXTex)
    target_link_libraries(cd-texture-dx PRIVATE DirectXTex)
else()
    message(FATAL_ERROR "DirectXTex was not found. Set DirectXTex_DIR or enable CDMW_FETCH_DIRECTXTEX.")
endif()
