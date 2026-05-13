cmake_minimum_required(VERSION 3.24)
project(cdmw_preview_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(cdmw-preview-core src/main.cpp)
target_compile_definitions(cdmw-preview-core PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
