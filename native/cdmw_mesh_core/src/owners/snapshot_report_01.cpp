int mesh_session_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, run_mesh_session(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
