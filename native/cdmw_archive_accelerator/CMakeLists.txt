cmake_minimum_required(VERSION 3.20)
project(cdmw_archive_accelerator LANGUAGES CXX)

add_executable(cdmw-archive-accelerator src/main.cpp)
target_compile_features(cdmw-archive-accelerator PRIVATE cxx_std_17)

