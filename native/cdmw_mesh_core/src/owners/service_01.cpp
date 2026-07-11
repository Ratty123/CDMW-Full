int run_service() {
    std::cout << "{\"event\":\"ready\",\"backend\":\"cdmw_mesh_core_0.1\"}" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            JsonParser parser(line);
            const JsonValue root = parser.parse();
            const std::string command = string_or(root.get("command"), "");
            if (command == "shutdown") {
                std::cout << "{\"event\":\"closed\",\"backend\":\"cdmw_mesh_core_0.1\"}" << std::endl;
                return 0;
            }
            if (command == "ping") {
                std::cout << "{\"event\":\"pong\",\"backend\":\"cdmw_mesh_core_0.1\"}" << std::endl;
                continue;
            }
            const JsonValue* inline_payload = root.get("payload");
            if (command == "mesh-editor-session-json" && inline_payload != nullptr && inline_payload->type == JsonValue::Type::Object) {
                int inline_exit_code = 0;
                const std::string report = mesh_editor_session_json_inline_report(*inline_payload, inline_exit_code);
                std::cout << "{\"status\":\"" << (inline_exit_code == 0 ? "ok" : "error")
                          << "\",\"backend\":\"cdmw_mesh_core_0.1\",\"inline_report\":" << report
                          << ",\"exit_code\":" << inline_exit_code << "}" << std::endl;
                continue;
            }
            const std::string job_path = string_or(root.get("job_path"), "");
            const std::string report_path = string_or(root.get("report_path"), "");
            if (command.empty() || job_path.empty() || report_path.empty()) {
                std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_mesh_core_0.1\",\"message\":\"missing command/job_path/report_path\"}" << std::endl;
                continue;
            }
            const int exit_code = mesh_core_json_command(command, job_path, report_path);
            std::cout << "{\"status\":\"" << (exit_code == 0 ? "ok" : "error")
                      << "\",\"backend\":\"cdmw_mesh_core_0.1\",\"report_path\":";
            write_escaped(std::cout, report_path);
            std::cout << ",\"exit_code\":" << exit_code << "}" << std::endl;
        } catch (const std::exception& exc) {
            std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_mesh_core_0.1\",\"message\":";
            write_escaped(std::cout, exc.what());
            std::cout << "}" << std::endl;
        }
    }
    return 0;
}
