cmake_minimum_required(VERSION 3.24)
project(cdmw_item_composer LANGUAGES CXX)

# Portable C++: no platform APIs, so the virtual loader can link it and any host can test it.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
# Match the virtual loader's static runtime so the library links into the ASI.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_library(cdmw_item_composer STATIC
    src/support.cpp
    src/lz4_block.cpp
    src/pabgh_table.cpp
    src/storeinfo.cpp
    src/itemgroupinfo.cpp
    src/paloc.cpp
    src/pappt.cpp
    src/pathc.cpp
    src/icon_registry.cpp
    src/overlay_merge.cpp
    src/checksum.cpp
    src/papgt.cpp
    src/overlay_archive.cpp
)
target_include_directories(cdmw_item_composer PUBLIC include PRIVATE src)

add_executable(cdmw_compose_cli tools/compose_cli.cpp)
target_link_libraries(cdmw_compose_cli PRIVATE cdmw_item_composer)

add_executable(cdmw_item_composer_self_test tests/self_test.cpp)
target_link_libraries(cdmw_item_composer_self_test PRIVATE cdmw_item_composer)
target_include_directories(cdmw_item_composer_self_test PRIVATE src)

foreach(target cdmw_item_composer cdmw_compose_cli cdmw_item_composer_self_test)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /WX /permissive- /EHsc /utf-8 /guard:cf)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endforeach()

enable_testing()
add_test(NAME cdmw-item-composer-self-test COMMAND cdmw_item_composer_self_test)
