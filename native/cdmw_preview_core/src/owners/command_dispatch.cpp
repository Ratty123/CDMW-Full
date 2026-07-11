int run_cli(int argc, char** argv) {
    CommonArgs common_args = parse_common_args(argc, argv);
    cdmw_native_diag::init("cdmw-preview-core", common_args.crash_dir, common_args.diagnostic_log);
    try {
        if (argc >= 2 && std::string(argv[1]) == "self-test") {
            cdmw_native_diag::event("self_test_ok");
            std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"cdmw_preview_core_0.1\"}\n";
            return 0;
        }
        if (argc >= 2 && std::string(argv[1]) == "--service") {
            return run_service();
        }
        if (argc >= 4 && std::string(argv[1]) == "preview-job") {
            return run_preview_job(fs::path(argv[2]), fs::path(argv[3]));
        }
        if (argc >= 4 && std::string(argv[1]) == "mesh-audit-job") {
            return run_mesh_audit_job(fs::path(argv[2]), fs::path(argv[3]), argc >= 5 ? std::string(argv[4]) : std::string());
        }
        if (argc >= 4 && std::string(argv[1]) == "mesh-parse-job") {
            return run_mesh_parse_job(fs::path(argv[2]), fs::path(argv[3]), argc >= 5 ? std::string(argv[4]) : std::string());
        }
        if (argc >= 5 && std::string(argv[1]) == "mesh-rebuild-job") {
            return run_mesh_rebuild_job(fs::path(argv[2]), fs::path(argv[3]), fs::path(argv[4]));
        }
        if (argc >= 5 && std::string(argv[1]) == "name-index-job") {
            return run_name_index_job(
                fs::path(argv[2]),
                fs::path(argv[3]),
                fs::path(argv[4]),
                argc >= 6 ? fs::path(argv[5]) : fs::path()
            );
        }
        std::cerr << "usage: cdmw-preview-core self-test | --service | preview-job <job.json> <report.json> | mesh-audit-job <input> <report.json> [filename] | mesh-parse-job <input> <report.json> [filename] | mesh-rebuild-job <job.json> <output.bin> <report.json> | name-index-job <input.tsv> <output.bin> <report.json> [progress.json]\n";
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
