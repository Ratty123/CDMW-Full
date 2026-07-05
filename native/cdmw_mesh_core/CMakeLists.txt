cmake_minimum_required(VERSION 3.20)
project(cdmw_mesh_core LANGUAGES C CXX)

add_executable(cdmw-mesh-core
    src/main.cpp
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
target_compile_features(cdmw-mesh-core PRIVATE cxx_std_17)
target_compile_definitions(cdmw-mesh-core PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_include_directories(cdmw-mesh-core PRIVATE third_party/mikktspace third_party/meshoptimizer third_party/ufbx third_party/xatlas)
