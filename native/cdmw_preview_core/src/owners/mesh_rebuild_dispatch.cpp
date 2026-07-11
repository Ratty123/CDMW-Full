struct MeshRebuildRequest {
    std::string job;
    std::string format;
    std::string filename;
    std::string layout;
    std::string mode;
    fs::path original_path;
};

static MeshRebuildRequest read_mesh_rebuild_request(const fs::path& job_path) {
    MeshRebuildRequest request;
    request.job = read_text(job_path);
    request.format = lower_copy(find_string_value(request.job, "target_format"));
    request.filename = find_string_value(request.job, "source_filename");
    request.layout = find_string_value(request.job, "layout");
    request.mode = find_string_value(request.job, "rebuild_mode");
    request.original_path = fs::path(find_string_value(request.job, "original_binary_path"));
    return request;
}

static void write_mesh_rebuild_binary(
    const fs::path& output_path,
    const std::vector<char>& rebuilt,
    const std::string& label
) {
    if (!output_path.parent_path().empty()) fs::create_directories(output_path.parent_path());
    std::ofstream output(output_path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("could not write native " + label + " output");
    output.write(rebuilt.data(), static_cast<std::streamsize>(rebuilt.size()));
    if (!output) throw std::runtime_error("native " + label + " output write failed");
}

static void write_mesh_rebuild_success(
    const fs::path& report_path,
    const fs::path& output_path,
    const MeshRebuildRequest& request,
    const std::vector<char>& rebuilt,
    bool include_full_mode
) {
    std::ostringstream report;
    report << "{\"status\":\"ok\","
           << "\"supported\":true,"
           << "\"backend\":\"cdmw_preview_core_mesh_audit_0.1\","
           << "\"command\":\"mesh-rebuild-job\","
           << "\"format\":\"" << json_escape(request.format) << "\","
           << "\"layout\":\"" << json_escape(request.layout) << "\","
           << "\"filename\":\"" << json_escape(request.filename) << "\",";
    if (include_full_mode) report << "\"rebuild_mode\":\"full\",";
    report << "\"rebuild_supported\":true,"
           << "\"parity_ready\":true,"
           << "\"bytes_written\":" << rebuilt.size() << ","
           << "\"output_path\":\"" << json_escape(output_path.string()) << "\","
           << "\"fallback_reason\":\"\"}";
    write_text(report_path, report.str());
}

static int run_pac_rebuild(
    const MeshRebuildRequest& request,
    const fs::path& output_path,
    const fs::path& report_path
) {
    if (request.mode == "full") {
        const fs::path submeshes = fs::path(find_string_value(request.job, "pac_full_submeshes_tsv_path"));
        const fs::path vertices = fs::path(find_string_value(request.job, "pac_full_vertices_tsv_path"));
        const fs::path faces = fs::path(find_string_value(request.job, "pac_full_faces_tsv_path"));
        if (request.original_path.empty() || submeshes.empty() || vertices.empty() || faces.empty()) {
            throw std::runtime_error("native PAC full rebuild job is missing patch table paths");
        }
        const std::vector<char> rebuilt = rebuild_pac_full_native(
            read_binary_file(request.original_path), load_pac_full_rebuild_tables(submeshes, vertices, faces));
        write_mesh_rebuild_binary(output_path, rebuilt, "PAC full rebuild");
        write_mesh_rebuild_success(report_path, output_path, request, rebuilt, true);
        return 0;
    }
    const fs::path submeshes = fs::path(find_string_value(request.job, "pac_submeshes_tsv_path"));
    const fs::path vertices = fs::path(find_string_value(request.job, "pac_vertices_tsv_path"));
    const fs::path faces = fs::path(find_string_value(request.job, "pac_faces_tsv_path"));
    if (request.original_path.empty() || submeshes.empty() || vertices.empty() || faces.empty()) {
        throw std::runtime_error("native PAC rebuild job is missing patch table paths");
    }
    const std::vector<char> rebuilt = rebuild_pac_in_place_native(
        read_binary_file(request.original_path), load_pac_patch_tables(submeshes, vertices, faces));
    write_mesh_rebuild_binary(output_path, rebuilt, "PAC rebuild");
    write_mesh_rebuild_success(report_path, output_path, request, rebuilt, false);
    return 0;
}

static bool supported_static_rebuild_layout(const MeshRebuildRequest& request) {
    return (request.format == "pam" && (
        request.layout == "native_pam_combined"
        || request.layout == "native_pam_local"
        || request.layout == "native_pam_scan_combined"
        || request.layout == "native_pam_backward_scan_combined"))
        || (request.format == "pamlod" && request.layout == "native_pamlod_lod0");
}

static int run_static_rebuild(
    const MeshRebuildRequest& request,
    const fs::path& output_path,
    const fs::path& report_path
) {
    if (request.format == "pamlod" && request.mode == "full") {
        const fs::path table = fs::path(find_string_value(request.job, "pamlod_full_rebuild_tsv_path"));
        if (request.original_path.empty() || table.empty()) {
            throw std::runtime_error("native PAMLOD full rebuild job is missing table paths");
        }
        const std::vector<char> rebuilt = rebuild_pamlod_lod0_full_native(
            read_binary_file(request.original_path), load_pamlod_full_rebuild_plan(table));
        write_mesh_rebuild_binary(output_path, rebuilt, "PAMLOD full rebuild");
        write_mesh_rebuild_success(report_path, output_path, request, rebuilt, true);
        return 0;
    }
    if (request.format == "pam" && request.mode == "full") {
        const fs::path table = fs::path(find_string_value(request.job, "static_full_rebuild_tsv_path"));
        if (request.original_path.empty() || table.empty()) {
            throw std::runtime_error("native PAM full rebuild job is missing table paths");
        }
        const std::vector<char> rebuilt = rebuild_pam_full_native(
            read_binary_file(request.original_path), load_pam_full_rebuild_plan(table));
        write_mesh_rebuild_binary(output_path, rebuilt, "PAM full rebuild");
        write_mesh_rebuild_success(report_path, output_path, request, rebuilt, true);
        return 0;
    }
    const fs::path patch = fs::path(find_string_value(request.job, "static_quantized_patch_tsv_path"));
    if (request.original_path.empty() || patch.empty()) {
        throw std::runtime_error("native static mesh rebuild job is missing patch table paths");
    }
    const std::vector<char> rebuilt = rebuild_static_quantized_in_place_native(
        read_binary_file(request.original_path), patch);
    write_mesh_rebuild_binary(output_path, rebuilt, "static mesh rebuild");
    write_mesh_rebuild_success(report_path, output_path, request, rebuilt, false);
    return 0;
}

static void write_mesh_rebuild_unsupported(
    const MeshRebuildRequest& request,
    const fs::path& output_path,
    const fs::path& report_path
) {
    std::ostringstream report;
    report << "{\"status\":\"unsupported\","
           << "\"supported\":false,"
           << "\"backend\":\"cdmw_preview_core_mesh_audit_0.1\","
           << "\"command\":\"mesh-rebuild-job\","
           << "\"format\":\"" << json_escape(request.format.empty() ? "unknown" : request.format) << "\","
           << "\"layout\":\"" << json_escape(request.layout.empty() ? "unproven" : request.layout) << "\","
           << "\"filename\":\"" << json_escape(request.filename) << "\","
           << "\"rebuild_supported\":false,"
           << "\"parity_ready\":false,"
           << "\"bytes_written\":0,"
           << "\"output_path\":\"" << json_escape(output_path.string()) << "\","
           << "\"fallback_reason\":\"native mesh rebuild is not enabled until per-layout parity tests pass\"}";
    write_text(report_path, report.str());
}

int run_mesh_rebuild_job(const fs::path& job_path, const fs::path& output_path, const fs::path& report_path) {
    try {
        const MeshRebuildRequest request = read_mesh_rebuild_request(job_path);
        if (request.format == "pac" && request.layout == "native_pac") {
            return run_pac_rebuild(request, output_path, report_path);
        }
        if (supported_static_rebuild_layout(request)) {
            return run_static_rebuild(request, output_path, report_path);
        }
        write_mesh_rebuild_unsupported(request, output_path, report_path);
        return 0;
    } catch (const std::exception& exc) {
        std::ostringstream report;
        report << "{\"status\":\"error\","
               << "\"supported\":false,"
               << "\"backend\":\"cdmw_preview_core_mesh_audit_0.1\","
               << "\"command\":\"mesh-rebuild-job\","
               << "\"format\":\"unknown\","
               << "\"layout\":\"unknown\","
               << "\"rebuild_supported\":false,"
               << "\"parity_ready\":false,"
               << "\"bytes_written\":0,"
               << "\"fallback_reason\":\"" << json_escape(exc.what()) << "\"}";
        try { write_text(report_path, report.str()); } catch (...) {}
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
