cmake_minimum_required(VERSION 3.24)
project(cdmw_full_archive_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(cdmw_full_archive_core SHARED
    src/archive_core.cpp
    src/archive_decode.cpp
    src/partial_dds.cpp
    src/pamt_index.cpp
)
target_compile_definitions(cdmw_full_archive_core PRIVATE
    CDMW_FULL_ARCHIVE_CORE_EXPORTS
    NOMINMAX
    WIN32_LEAN_AND_MEAN
)
target_include_directories(cdmw_full_archive_core
    PUBLIC include
    PRIVATE src
)
set_target_properties(cdmw_full_archive_core PROPERTIES
    OUTPUT_NAME "cdmw-full-archive-core"
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
)

add_executable(cdmw-full-archive-core-self-test
    tests/archive_core_tests.cpp
    src/archive_decode.cpp
    src/partial_dds.cpp
)
target_link_libraries(cdmw-full-archive-core-self-test PRIVATE cdmw_full_archive_core)
target_include_directories(cdmw-full-archive-core-self-test PRIVATE include src)
set_target_properties(cdmw-full-archive-core-self-test PROPERTIES
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
)

foreach(cdmw_full_archive_target cdmw_full_archive_core cdmw-full-archive-core-self-test)
    if(MSVC)
        target_compile_options(${cdmw_full_archive_target} PRIVATE /W4 /WX /permissive- /utf-8)
    else()
        target_compile_options(${cdmw_full_archive_target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endforeach()

enable_testing()
add_test(NAME cdmw-full-archive-core-self-test COMMAND cdmw-full-archive-core-self-test)
