cmake_minimum_required(VERSION 3.24)
project(cd_texture_dx LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(CDMW_FETCH_DIRECTXTEX "Fetch Microsoft DirectXTex when it is not provided by DirectXTex_DIR" ON)

find_package(DirectXTex CONFIG QUIET)
if(NOT DirectXTex_FOUND AND CDMW_FETCH_DIRECTXTEX)
    include(FetchContent)
    FetchContent_Declare(
        directxtex
        GIT_REPOSITORY https://github.com/microsoft/DirectXTex.git
        GIT_TAG main
    )
    FetchContent_MakeAvailable(directxtex)
endif()

add_executable(cd-texture-dx src/main.cpp)
target_compile_definitions(cd-texture-dx PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_link_libraries(cd-texture-dx PRIVATE windowscodecs)

if(TARGET Microsoft::DirectXTex)
    target_link_libraries(cd-texture-dx PRIVATE Microsoft::DirectXTex)
elseif(TARGET DirectXTex)
    target_link_libraries(cd-texture-dx PRIVATE DirectXTex)
else()
    message(FATAL_ERROR "DirectXTex was not found. Set DirectXTex_DIR or enable CDMW_FETCH_DIRECTXTEX.")
endif()
