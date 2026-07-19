
static size_t resident_preview_metadata_cache_count() {
    return resident_pathc_cache_count()
        + resident_material_graph_metadata_count()
        + resident_parsed_material_sidecar_cache_count();
}

static void release_resident_preview_metadata_caches() {
    release_resident_pathc_cache();
    release_resident_material_graph_metadata();
    release_resident_parsed_material_sidecar_cache();
}

struct PreviewCacheReleaseStats {
    size_t pamt_before = 0;
    size_t pamt_after = 0;
    size_t metadata_before = 0;
    size_t metadata_after = 0;
    size_t archive_lite_lookup_before = 0;
    size_t archive_lite_lookup_after = 0;
};

static PreviewCacheReleaseStats release_preview_job_caches() {
    PreviewCacheReleaseStats stats;
    stats.pamt_before = resident_pamt_index_count();
    stats.metadata_before = resident_preview_metadata_cache_count();
    stats.archive_lite_lookup_before = resident_archive_lite_lookup_count();
    release_resident_pamt_indexes();
    release_resident_preview_metadata_caches();
    release_resident_archive_lite_lookup();
    stats.pamt_after = resident_pamt_index_count();
    stats.metadata_after = resident_preview_metadata_cache_count();
    stats.archive_lite_lookup_after = resident_archive_lite_lookup_count();
    return stats;
}

static void append_preview_cache_release_report(
    std::ostringstream& out,
    const PreviewCacheReleaseStats& stats
) {
    out << "\"native_pamt_index_resident_before_release\":" << stats.pamt_before << ","
        << "\"native_pamt_index_resident_after_release\":" << stats.pamt_after << ","
        << "\"native_pamt_index_cache_released\":" << (stats.pamt_after == 0 ? "true" : "false") << ","
        << "\"native_metadata_cache_resident_before_release\":" << stats.metadata_before << ","
        << "\"native_metadata_cache_resident_after_release\":" << stats.metadata_after << ","
        << "\"native_metadata_cache_released\":" << (stats.metadata_after == 0 ? "true" : "false") << ",";
    out << "\"archive_lite_lookup_resident_before_release\":" << stats.archive_lite_lookup_before << ","
        << "\"archive_lite_lookup_resident_after_release\":" << stats.archive_lite_lookup_after << ","
        << "\"archive_lite_lookup_released\":" << (stats.archive_lite_lookup_after == 0 ? "true" : "false") << ",";
}

static NativePackage try_generate_native_package(const EntryJob& job, const std::vector<char>& data) {
    NativePackage package;
    NativeMeshParseResult parsed;
    const auto pamt_index_started = std::chrono::steady_clock::now();
    const PamtIndex& index = cached_pamt_index(job.entry.pamt_path, job.cache_root);
    package.pamt_index_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - pamt_index_started).count();
    package.pamt_index_entries = index.entry_count;
    package.pamt_index_cache_hit = index.persistent_cache_hit;
    package.pamt_index_cache_path = index.persistent_cache_path.string();
    if (job.extension == ".pac") {
        parsed.meshes = parse_pac_submeshes(data);
        parsed.parser = "native_pac_par_sections";
        for (size_t mesh_index = 0; mesh_index < parsed.meshes.size(); ++mesh_index) {
            NativeSubmesh& mesh = parsed.meshes[mesh_index];
            mesh.source_model_path = job.path;
            mesh.source_component_label = job.entry.basename.empty() ? basename_from_path(job.path) : job.entry.basename;
            mesh.source_component_index = 0;
            mesh.source_prefab_component = false;
            if (mesh.source_local_submesh_index < 0) mesh.source_local_submesh_index = mesh.source_submesh_index;
            mesh.source_submesh_index = static_cast<int>(mesh_index);
        }
        int component_models_added = 0;
        int component_batches_added = 0;
        for (const ArchiveEntryRef& component : prefab_model_component_refs_for_job(job, index, 8)) {
            if (lower_copy(component.path) == lower_copy(job.path)) continue;
            try {
                const std::vector<char> component_data = read_archive_ref_decoded_bytes(component);
                NativeMeshParseResult component_parse;
                if (component.extension == ".pac") {
                    component_parse.meshes = parse_pac_submeshes(component_data);
                    component_parse.parser = "native_pac_par_sections";
                } else if (component.extension == ".pam") {
                    component_parse = parse_pam_submeshes(component_data);
                } else if (component.extension == ".pamlod") {
                    component_parse = parse_pamlod_submeshes(component_data);
                }
                if (component_parse.meshes.empty()) continue;
                const int component_index = component_models_added + 1;
                const int global_submesh_offset = static_cast<int>(parsed.meshes.size());
                for (size_t mesh_index = 0; mesh_index < component_parse.meshes.size(); ++mesh_index) {
                    NativeSubmesh& mesh = component_parse.meshes[mesh_index];
                    mesh.source_model_path = component.path;
                    mesh.source_component_label = component.basename.empty() ? basename_from_path(component.path) : component.basename;
                    mesh.source_component_index = component_index;
                    mesh.source_prefab_component = true;
                    if (mesh.source_local_submesh_index < 0) mesh.source_local_submesh_index = mesh.source_submesh_index;
                    mesh.source_submesh_index = global_submesh_offset + static_cast<int>(mesh_index);
                }
                component_batches_added += static_cast<int>(component_parse.meshes.size());
                parsed.meshes.insert(
                    parsed.meshes.end(),
                    std::make_move_iterator(component_parse.meshes.begin()),
                    std::make_move_iterator(component_parse.meshes.end()));
                ++component_models_added;
                add_asset_family_row(package, NativeAssetFamilyRow{
                    "Prefab / Components",
                    "Model Component",
                    component.basename.empty() ? basename_from_path(component.path) : component.basename,
                    component.path,
                    "Resolved",
                    "Prefab",
                    "authoritative",
                    "required",
                    "Native preview-core expanded a same-stem item prefab component into the D3D11 package.",
                    "model",
                    "Prefab model component",
                    "",
                    "",
                    "",
                    package_label_for_ref(component),
                    component.extension,
                    "",
                    "",
                    "",
                    ""
                });
            } catch (const std::exception& exc) {
                package.notes.push_back("native prefab composite component skipped:" + component.path + ":" + exc.what());
            }
        }
        if (component_models_added > 0) {
            parsed.parser += "+prefab_composite";
            package.notes.push_back(
                "native prefab composite: added " + std::to_string(component_models_added) +
                " referenced model component(s), " + std::to_string(component_batches_added) +
                " batch(es), from same-stem item prefab"
            );
        }
    } else if (job.extension == ".pam") {
        parsed = parse_pam_submeshes(data);
    } else if (job.extension == ".pamlod") {
        parsed = parse_pamlod_submeshes(data);
    } else {
        throw std::runtime_error("native preview-core package generation only supports .pac, .pam, and .pamlod");
    }
    if (parsed.meshes.empty()) {
        throw std::runtime_error("native model parser found no renderable geometry");
    }
    for (size_t mesh_index = 0; mesh_index < parsed.meshes.size(); ++mesh_index) {
        NativeSubmesh& mesh = parsed.meshes[mesh_index];
        if (mesh.source_model_path.empty()) mesh.source_model_path = job.path;
        if (mesh.source_component_label.empty()) mesh.source_component_label = job.entry.basename.empty() ? basename_from_path(job.path) : job.entry.basename;
        if (mesh.source_local_submesh_index < 0) mesh.source_local_submesh_index = mesh.source_submesh_index;
        if (mesh.source_submesh_index < 0) mesh.source_submesh_index = static_cast<int>(mesh_index);
    }
    package.mesh_parse = parsed.parser;
    package.lod_count = parsed.lod_count;
    std::vector<TextureBinding> bindings;
    if (job.use_textures) {
        bindings = build_material_bindings(job, index, parsed.meshes, package);
        append_mesh_reference_bindings(job, index, parsed.meshes, bindings, package);
    } else {
        package.material_index = "disabled";
        package.material_graph_status = "disabled";
        package.texture_resolution = "disabled";
        package.material_output_quality = "disabled";
        package.material_quality_safe = true;
        package.notes.push_back("native package emitted geometry-only preview because textures were disabled by job settings");
    }
    if (bindings.empty() && job.use_textures) {
        if (package.material_index.empty()) package.material_index = "none";
        package.texture_resolution = "none";
        package.notes.push_back("native package emitted geometry with fallback batch colors because no direct DDS bindings were resolved");
    }
    return write_d3d11_package(job, parsed.meshes, bindings, package);
}

std::string preview_report_for_job(const fs::path& job_path) {
    const auto started = std::chrono::steady_clock::now();
    reset_archive_lite_lookup_diagnostics();
    EntryJob job = parse_job(job_path);
    std::string status = "unsupported";
    std::string fallback_reason;
    std::string message;
    std::string format_fourcc;
    std::uint64_t bytes_read = 0;
    const int compression_type = static_cast<int>(job.flags & 0x0F);
    bool raw_read_ok = false;
    NativePackage package;
    const std::uint64_t cache_hits_before = decoded_entry_cache_hits();
    const std::uint64_t cache_misses_before = decoded_entry_cache_misses();
    const std::uint64_t cache_evictions_before = decoded_entry_cache_evictions();
    const std::uint64_t sidecar_cache_hits_before = sidecar_parse_cache_hits();
    const std::uint64_t sidecar_cache_misses_before = sidecar_parse_cache_misses();
    try {
        fs::create_directories(job.output_root);
        fs::create_directories(job.cache_root);
        auto data = read_entry_decoded_bytes(job);
        bytes_read = static_cast<std::uint64_t>(data.size());
        format_fourcc = fourcc_from_bytes(data);
        raw_read_ok = true;
        if (job.extension != ".pam" && job.extension != ".pamlod" && job.extension != ".pac") {
            fallback_reason = "selected entry is not a native-preview-core model target";
        } else if (compression_type != 0 && compression_type != 1 && compression_type != 2 && job.comp_size != job.orig_size) {
            fallback_reason = "native decompression/reconstruction is not enabled for this milestone";
        } else {
            try {
                package = try_generate_native_package(job, data);
                if (package.batch_count > 0 && !package.path.empty()) {
                    status = "ok";
                    fallback_reason.clear();
                    message = "native preview-core generated a D3D11 package";
                } else {
                    fallback_reason = "native preview-core generated no renderable batches";
                }
            } catch (const std::exception& native_exc) {
                fallback_reason = native_exc.what();
            }
        }
        if (message.empty()) {
            message = status == "ok"
                ? "native preview-core generated a D3D11 package"
                : "native preview-core did not generate a D3D11 package";
        }
    } catch (const std::exception& exc) {
        status = "error";
        fallback_reason = exc.what();
        message = "native archive IO preflight failed";
    }
    const PreviewCacheReleaseStats cache_release = release_preview_job_caches();
    const cdmw_native_diag::ProcessMemorySnapshot memory = cdmw_native_diag::current_process_memory();
    const std::string recycle_reason = service_recycle_reason(memory);
    const double elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    std::ostringstream out;
    out << "{"
        << "\"status\":\"" << json_escape(status) << "\","
        << "\"backend\":\"cdmw_preview_core_0.1\","
        << "\"runtime_backend\":\"native_cpp\","
        << "\"package_builder\":\"cdmw_preview_core_cpp\","
        << "\"renderer_contract\":\"d3d11_native_package\","
        << "\"python_fallback_allowed\":false,"
        << "\"native_archive_io\":\"" << (raw_read_ok ? "ok" : "failed") << "\","
        << "\"native_mesh_parser\":\"" << json_escape(package.mesh_parse.empty() ? "pending" : package.mesh_parse) << "\","
        << "\"native_material_index\":\"" << json_escape(package.material_index.empty() ? "pending" : package.material_index) << "\","
        << "\"native_material_graph_status\":\"" << json_escape(package.material_graph_status) << "\","
        << "\"native_material_graph_cache_hit\":" << (package.material_graph_cache_hit ? "true" : "false") << ","
        << "\"native_material_graph_cache_path\":\"" << json_escape(package.material_graph_cache_path) << "\","
        << "\"native_texture_resolution\":\"" << json_escape(package.texture_resolution.empty() ? "pending" : package.texture_resolution) << "\","
        << "\"native_material_output_quality\":\"" << json_escape(package.material_output_quality.empty() ? "pending" : package.material_output_quality) << "\","
        << "\"material_quality_safe\":" << (package.material_quality_safe ? "true" : "false") << ","
        << "\"base_missing_count\":" << package.base_missing_count << ","
        << "\"base_low_res_count\":" << package.base_low_res_count << ","
        << "\"base_low_confidence_count\":" << package.base_low_confidence_count << ","
        << "\"base_technical_count\":" << package.base_technical_count << ","
        << "\"schema_version\":" << std::max(kNativePackageSchemaVersion, job.schema_version) << ","
        << "\"material_semantics_version\":" << kNativeMaterialSemanticsVersion << ","
        << "\"material_graph_version\":" << kNativeMaterialGraphVersion << ","
        << "\"visible_texture_mode\":\"" << json_escape(job.visible_texture_mode) << "\","
        << "\"entry_path\":\"" << json_escape(job.path) << "\","
        << "\"extension\":\"" << json_escape(job.extension) << "\","
        << "\"format_fourcc\":\"" << json_escape(format_fourcc) << "\","
        << "\"compression_type\":" << compression_type << ","
        << "\"bytes_read\":" << bytes_read << ","
        << "\"batch_count\":" << package.batch_count << ","
        << "\"vertex_count\":" << package.vertex_count << ","
        << "\"face_count\":" << package.face_count << ","
        << "\"lod_count\":" << package.lod_count << ","
        << "\"dds_candidates\":" << package.dds_candidates << ","
        << "\"dds_extracted\":" << package.dds_extracted << ","
        << "\"native_pamt_index_ms\":" << package.pamt_index_ms << ","
        << "\"native_pamt_index_entries\":" << package.pamt_index_entries << ","
        << "\"native_pamt_index_cache_hit\":" << (package.pamt_index_cache_hit ? "true" : "false") << ","
        << "\"native_pamt_index_cache_path\":\"" << json_escape(package.pamt_index_cache_path) << "\",";
    append_preview_cache_release_report(out, cache_release);
    out << "\"asset_family_reference_count\":" << package.asset_family_reference_count << ","
        << "\"archive_lookup_backend\":\"" << json_escape(archive_lite_lookup_backend()) << "\","
        << "\"archive_lookup_queries\":" << g_archive_lite_lookup_queries << ","
        << "\"archive_lookup_candidates\":" << g_archive_lite_lookup_candidates << ","
        << "\"archive_lookup_error\":\"" << json_escape(g_archive_lite_lookup_error) << "\","
        << "\"decoded_cache_entries\":" << decoded_entry_cache_entries() << ","
        << "\"decoded_cache_bytes\":" << decoded_entry_cache_bytes() << ","
        << "\"decoded_cache_hits\":" << decoded_entry_cache_hits() << ","
        << "\"decoded_cache_misses\":" << decoded_entry_cache_misses() << ","
        << "\"decoded_cache_evictions\":" << decoded_entry_cache_evictions() << ","
        << "\"decoded_cache_job_hits\":" << (decoded_entry_cache_hits() - cache_hits_before) << ","
        << "\"decoded_cache_job_misses\":" << (decoded_entry_cache_misses() - cache_misses_before) << ","
        << "\"decoded_cache_job_evictions\":" << (decoded_entry_cache_evictions() - cache_evictions_before) << ","
        << "\"sidecar_parse_cache_hits\":" << sidecar_parse_cache_hits() << ","
        << "\"sidecar_parse_cache_misses\":" << sidecar_parse_cache_misses() << ","
        << "\"sidecar_parse_cache_job_hits\":" << (sidecar_parse_cache_hits() - sidecar_cache_hits_before) << ","
        << "\"sidecar_parse_cache_job_misses\":" << (sidecar_parse_cache_misses() - sidecar_cache_misses_before) << ","
        << "\"process_working_set_bytes\":" << (memory.ok ? memory.working_set_bytes : 0ull) << ","
        << "\"process_private_bytes\":" << (memory.ok ? memory.private_bytes : 0ull) << ","
        << "\"service_job_count\":" << g_service_job_count << ","
        << "\"service_recycle_reason\":\"" << json_escape(recycle_reason) << "\","
        << "\"elapsed_ms\":" << elapsed_ms << ","
        << "\"package_path\":\"" << json_escape(status == "ok" ? package.path.string() : "") << "\","
        << "\"fallback_reason\":\"" << json_escape(fallback_reason) << "\","
        << "\"message\":\"" << json_escape(message) << "\","
        << "\"base_quality_notes\":[";
    for (size_t i = 0; i < package.base_quality_notes.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.base_quality_notes[i]) << "\"";
    }
    out << "],"
        << "\"selected_texture_examples\":[";
    for (size_t i = 0; i < package.selected_texture_examples.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.selected_texture_examples[i]) << "\"";
    }
    out << "],"
        << "\"rejected_texture_examples\":[";
    for (size_t i = 0; i < package.rejected_texture_examples.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.rejected_texture_examples[i]) << "\"";
    }
    out << "],"
        << "\"notes\":[";
    for (size_t i = 0; i < package.notes.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.notes[i]) << "\"";
    }
    out << "]"
        << "}";
    return out.str();
}

struct CommonArgs {
    fs::path crash_dir;
    fs::path diagnostic_log;
};

CommonArgs parse_common_args(int argc, char** argv) {
    CommonArgs args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i] ? argv[i] : "";
        auto next = [&]() -> fs::path {
            if (i + 1 >= argc) return {};
            return fs::path(argv[++i]);
        };
        if (key == "--crash-dir") args.crash_dir = next();
        else if (key == "--diagnostic-log") args.diagnostic_log = next();
    }
    return args;
}

int run_preview_job(const fs::path& job_path, const fs::path& report_path) {
    try {
        cdmw_native_diag::event(
            "preview_job_start",
            {
                {"job_path", cdmw_native_diag::path_to_utf8(job_path)},
                {"report_path", cdmw_native_diag::path_to_utf8(report_path)},
                {"service_job_count", std::to_string(g_service_job_count)}
            });
        write_text(report_path, preview_report_for_job(job_path));
        const cdmw_native_diag::ProcessMemorySnapshot memory = cdmw_native_diag::current_process_memory();
        cdmw_native_diag::event(
            "preview_job_complete",
            {
                {"job_path", cdmw_native_diag::path_to_utf8(job_path)},
                {"report_path", cdmw_native_diag::path_to_utf8(report_path)},
                {"decoded_cache_entries", std::to_string(decoded_entry_cache_entries())},
                {"decoded_cache_bytes", std::to_string(decoded_entry_cache_bytes())},
                {"decoded_cache_hits", std::to_string(decoded_entry_cache_hits())},
                {"decoded_cache_misses", std::to_string(decoded_entry_cache_misses())},
                {"decoded_cache_evictions", std::to_string(decoded_entry_cache_evictions())},
                {"service_job_count", std::to_string(g_service_job_count)},
                {"service_recycle_reason", service_recycle_reason(memory)}
            });
        return 0;
    } catch (const std::exception& exc) {
        release_resident_pamt_indexes();
        release_resident_preview_metadata_caches();
        std::ostringstream out;
        out << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\""
            << json_escape(exc.what()) << "\",\"fallback_reason\":\"" << json_escape(exc.what()) << "\"}";
        try {
            write_text(report_path, out.str());
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        cdmw_native_diag::event("preview_job_error", {{"job_path", cdmw_native_diag::path_to_utf8(job_path)}, {"message", exc.what()}});
        return 2;
    }
}

int run_mesh_audit_job(const fs::path& input_path, const fs::path& report_path, const std::string& filename) {
    try {
        std::vector<char> data = read_binary_file(input_path);
        const std::string lowered = lower_copy(filename);
        std::string format = "pam";
        NativeMeshParseResult parsed;
        if (lowered.ends_with(".pac")) {
            format = "pac";
            parsed.meshes = parse_pac_submeshes(data);
            parsed.parser = "native_pac";
        } else if (lowered.ends_with(".pamlod")) {
            format = "pamlod";
            parsed = parse_pamlod_submeshes(data);
        } else {
            parsed = parse_pam_submeshes(data);
        }
        std::uint64_t vertex_count = 0;
        std::uint64_t index_count = 0;
        int safe_mesh_count = 0;
        for (const NativeSubmesh& mesh : parsed.meshes) {
            vertex_count += static_cast<std::uint64_t>(mesh.positions.size());
            index_count += static_cast<std::uint64_t>(mesh.indices.size());
            if (mesh.geometry_safe) ++safe_mesh_count;
        }
        std::ostringstream out;
        out << "{\"status\":\"ok\","
            << "\"backend\":\"cdmw_preview_core_mesh_audit_0.1\","
            << "\"parser\":\"" << json_escape(parsed.parser) << "\","
            << "\"format\":\"" << json_escape(format) << "\","
            << "\"layout\":\"" << json_escape(parsed.parser) << "\","
            << "\"filename\":\"" << json_escape(filename) << "\","
            << "\"submesh_count\":" << parsed.meshes.size() << ","
            << "\"safe_submesh_count\":" << safe_mesh_count << ","
            << "\"vertex_count\":" << vertex_count << ","
            << "\"index_count\":" << index_count << ","
            << "\"face_count\":" << (index_count / 3u) << ","
            << "\"lod_count\":" << parsed.lod_count << ","
            << "\"supported\":true,"
            << "\"rebuild_supported\":false,"
            << "\"parity_ready\":false,"
            << "\"bytes_written\":0,"
            << "\"fallback_reason\":\"native mesh rebuild parity is not enabled for this layout\","
            << "\"rebuild_enabled\":false}";
        write_text(report_path, out.str());
        return 0;
    } catch (const std::exception& exc) {
        std::ostringstream out;
        out << "{\"status\":\"error\","
            << "\"supported\":false,"
            << "\"backend\":\"cdmw_preview_core_mesh_audit_0.1\","
            << "\"message\":\"" << json_escape(exc.what()) << "\","
            << "\"format\":\"unknown\","
            << "\"layout\":\"unknown\","
            << "\"rebuild_supported\":false,"
            << "\"parity_ready\":false,"
            << "\"bytes_written\":0,"
            << "\"fallback_reason\":\"" << json_escape(exc.what()) << "\","
            << "\"rebuild_enabled\":false}";
        try {
            write_text(report_path, out.str());
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int run_mesh_parse_job(const fs::path& input_path, const fs::path& report_path, const std::string& filename) {
    return run_mesh_audit_job(input_path, report_path, filename);
}
