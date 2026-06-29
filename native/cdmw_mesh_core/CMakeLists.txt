cmake_minimum_required(VERSION 3.20)
project(cdmw_mesh_core LANGUAGES CXX)

add_executable(cdmw-mesh-core src/main.cpp)
target_compile_features(cdmw-mesh-core PRIVATE cxx_std_17)
target_compile_definitions(cdmw-mesh-core PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
