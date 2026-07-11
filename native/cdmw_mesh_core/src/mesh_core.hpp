#pragma once

#include <string>

namespace cdmw_mesh_core {

int mesh_core_json_command(
    const std::string& command,
    const std::string& job_path,
    const std::string& report_path
);
int run_service();

}  // namespace cdmw_mesh_core
