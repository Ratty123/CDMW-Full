static void add_package_asset_family_rows(PackageWriteState& state) {
    add_asset_family_row(state.package, NativeAssetFamilyRow{
        "Selected Model", "Model",
        state.job.entry.basename.empty() ? basename_from_path(state.job.path) : state.job.entry.basename,
        state.job.path, "Model OK", "Selected", "exact_path", "required",
        "The file currently selected in Archive Browser.", "model", "Selected model",
        "", "", "", package_label_for_ref(state.job.entry), "", "", "", "", ""
    });
    const std::string model_stem = stem_from_path(state.job.path);
    const std::vector<std::pair<std::string, std::pair<std::string, std::string>>> related_basenames = {
        {model_stem + ".meshinfo", {"MeshInfo", "Meshinfo"}},
        {model_stem + ".hkx", {"Physics / HKX", "HKX / Physics"}},
        {model_stem + ".prefab", {"Prefab / Metadata", "Prefab"}},
        {model_stem + "_l.prefab", {"Prefab / Metadata", "Prefab"}},
        {model_stem + "_r.prefab", {"Prefab / Metadata", "Prefab"}},
        {model_stem + ".prefabdata_xml", {"Prefab / Metadata", "Prefab Data"}},
        {model_stem + "_l.prefabdata_xml", {"Prefab / Metadata", "Prefab Data"}},
        {model_stem + "_r.prefabdata_xml", {"Prefab / Metadata", "Prefab Data"}},
        {model_stem + ".sockets.xml", {"Attachment / Placement", "Socket XML"}},
        {model_stem + "_l.sockets.xml", {"Attachment / Placement", "Socket XML"}},
        {model_stem + "_r.sockets.xml", {"Attachment / Placement", "Socket XML"}},
        {model_stem + ".pab", {"Skeleton / Rig", "Skeleton"}},
    };
    for (const auto& related : related_basenames) {
        for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(
            state.job, *state.package_index, related.first, 8)) {
            add_asset_family_row(state.package, NativeAssetFamilyRow{
                related.second.first, related.second.second,
                ref.basename.empty() ? basename_from_path(ref.path) : ref.basename,
                ref.path, "Resolved", "Same stem", "derived_same_stem", "manual",
                "Native preview-core found a same-stem related archive entry.",
                "metadata", related.second.second, "", "", "", package_label_for_ref(ref),
                ref.extension, "", "", "", ""
            });
        }
    }
    for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(
        state.job, *state.package_index, "identityskeleton.pab", 4)) {
        add_asset_family_row(state.package, NativeAssetFamilyRow{
            "Skeleton / Rig", "Skeleton",
            ref.basename.empty() ? basename_from_path(ref.path) : ref.basename,
            ref.path, "Resolved", "Name hint", "derived_family_heuristic", "manual",
            "Native preview-core found the common identity skeleton companion.",
            "skeleton", "Skeleton", "", "", "", package_label_for_ref(ref), ref.extension,
            "", "", "", ""
        });
    }
    state.package.asset_family_reference_count = std::max(
        0, static_cast<int>(state.package.asset_family_rows.size()) - 1);
}

static std::string package_manifest_json(const PackageWriteState& state) {
    const std::string format = state.job.extension.size() > 1 && state.job.extension.front() == '.'
        ? state.job.extension.substr(1) : state.job.extension;
    const std::string lighting_preset = native_lighting_preset_for_job(
        state.job, state.has_metal_preview_response);
    std::ostringstream manifest;
    manifest << "{"
        << "\"schema_version\":" << std::max(kNativePackageSchemaVersion, state.job.schema_version) << ","
        << "\"material_semantics_version\":" << kNativeMaterialSemanticsVersion << ","
        << "\"material_graph_version\":" << kNativeMaterialGraphVersion << ","
        << "\"backend\":\"d3d11\","
        << "\"source_path\":\"" << json_escape(state.job.path) << "\","
        << "\"format\":\"" << json_escape(format) << "\","
        << "\"summary\":\"Native preview-core " << json_escape(format) << " package\","
        << "\"visible_texture_mode\":\"" << json_escape(state.job.visible_texture_mode) << "\","
        << "\"render_diagnostic_mode\":\"" << json_escape(state.job.render_diagnostic_mode) << "\","
        << "\"d3d11_view_mode\":\"" << json_escape(state.job.d3d11_view_mode) << "\","
        << "\"lighting_preset\":\"" << json_escape(lighting_preset) << "\","
        << "\"material_contract_schema\":2,"
        << "\"material_channel_contract_schema\":2,"
        << "\"texture_quality_schema\":1,"
        << "\"mesh_count\":" << state.emitted_batch_count << ","
        << "\"source_vertex_count\":" << state.geometry.source_vertex_count << ","
        << "\"vertex_count\":" << state.emitted_vertex_count << ","
        << "\"face_count\":" << state.geometry.face_count << ","
        << "\"normalization_center\":[" << state.geometry.center.x << "," << state.geometry.center.y << "," << state.geometry.center.z << "],"
        << "\"normalization_scale\":" << state.geometry.scale << ","
        << "\"orbit_sensitivity\":" << state.job.orbit_sensitivity << ","
        << "\"pan_sensitivity\":" << state.job.pan_sensitivity << ","
        << "\"invert_orbit_x\":" << (state.job.invert_orbit_x ? "true" : "false") << ","
        << "\"invert_orbit_y\":" << (state.job.invert_orbit_y ? "true" : "false") << ","
        << "\"invert_pan_x\":" << (state.job.invert_pan_x ? "true" : "false") << ","
        << "\"invert_pan_y\":" << (state.job.invert_pan_y ? "true" : "false") << ","
        << "\"max_anisotropy\":" << state.job.max_anisotropy << ","
        << "\"d3d11_mip_lod_bias\":" << state.job.d3d11_mip_lod_bias << ","
        << "\"d3d11_cull_back_faces\":" << (state.job.d3d11_cull_back_faces ? "true" : "false") << ","
        << "\"d3d11_light_azimuth_degrees\":" << state.job.d3d11_light_azimuth_degrees << ","
        << "\"d3d11_light_elevation_degrees\":" << state.job.d3d11_light_elevation_degrees << ","
        << "\"d3d11_normal_y_mode\":\"" << json_escape(state.job.d3d11_normal_y_mode) << "\","
        << "\"d3d11_ao_strength\":" << state.job.d3d11_ao_strength << ","
        << "\"d3d11_roughness_bias\":" << state.job.d3d11_roughness_bias << ","
        << "\"d3d11_metalness_scale\":" << state.job.d3d11_metalness_scale << ","
        << "\"d3d11_environment_strength\":" << state.job.d3d11_environment_strength << ","
        << "\"d3d11_emissive_gain\":" << state.job.d3d11_emissive_gain << ","
        << "\"d3d11_tone_exposure\":" << state.job.d3d11_tone_exposure << ","
        << "\"d3d11_tone_contrast\":" << state.job.d3d11_tone_contrast << ","
        << "\"d3d11_tone_gamma\":" << state.job.d3d11_tone_gamma << ","
        << "\"d3d11_texture_address_mode\":\"" << json_escape(state.job.d3d11_texture_address_mode) << "\","
        << "\"ambient_strength\":" << state.job.ambient_strength << ","
        << "\"diffuse_wrap_bias\":" << state.job.diffuse_wrap_bias << ","
        << "\"diffuse_light_scale\":" << state.job.diffuse_light_scale << ","
        << "\"specular_base\":" << state.job.specular_base << ","
        << "\"specular_max\":" << state.job.specular_max << ","
        << "\"shininess_min\":" << state.job.shininess_min << ","
        << "\"shininess_max\":" << state.job.shininess_max << ","
        << "\"use_textures\":" << (state.job.use_textures ? "true" : "false") << ","
        << "\"high_quality_textures\":" << (state.job.high_quality_textures ? "true" : "false") << ","
        << "\"native_preview_core\":{\"runtime_backend\":\"native_cpp\",\"package_builder\":\"cdmw_preview_core_cpp\",\"renderer_contract\":\"d3d11_native_package\",\"python_fallback_allowed\":false,\"mesh_parse\":\"" << json_escape(state.package.mesh_parse) << "\",\"material_index\":\"" << json_escape(state.package.material_index) << "\",\"material_graph_status\":\"" << json_escape(state.package.material_graph_status) << "\",\"material_graph_version\":" << kNativeMaterialGraphVersion << ",\"material_graph_cache_hit\":" << (state.package.material_graph_cache_hit ? "true" : "false") << ",\"material_graph_cache_path\":\"" << json_escape(state.package.material_graph_cache_path) << "\",\"texture_resolution\":\"" << json_escape(state.package.texture_resolution) << "\",\"material_output_quality\":\"" << json_escape(state.package.material_output_quality) << "\",\"material_semantics_version\":" << kNativeMaterialSemanticsVersion << ",\"material_quality_safe\":" << (state.package.material_quality_safe ? "true" : "false") << ",\"base_missing_count\":" << state.package.base_missing_count << ",\"base_low_res_count\":" << state.package.base_low_res_count << ",\"base_low_confidence_count\":" << state.package.base_low_confidence_count << ",\"base_technical_count\":" << state.package.base_technical_count << ",\"asset_family_reference_count\":" << state.package.asset_family_reference_count << ",\"visible_texture_mode\":\"" << json_escape(state.job.visible_texture_mode) << "\",\"lod_count\":" << state.package.lod_count << "},"
        << native_asset_family_json(state.package, state.job) << ","
        << "\"material_slots\":[" << state.material_slots_json.str() << "],"
        << "\"selection_decisions\":[" << state.selection_decisions_json.str() << "],"
        << "\"rejected_candidates\":[";
    for (size_t index = 0; index < state.package.rejected_texture_examples.size(); ++index) {
        if (index) manifest << ",";
        manifest << "\"" << json_escape(state.package.rejected_texture_examples[index]) << "\"";
    }
    manifest << "],"
        << "\"dds_upload_policy\":{\"default\":\"direct_dds\",\"png_fallback\":\"generated_or_non_dds_only\",\"base_srgb\":\"from_technique_or_role\",\"data_maps\":\"linear\",\"normal_y_policy\":\"per_batch\"},"
        << "\"pbd_hint_count\":" << state.package.pbd_hint_count << ","
        << "\"pbd_soft_hint_count\":" << state.package.pbd_soft_hint_count << ","
        << "\"pbd_cloth_hint_count\":" << state.package.pbd_cloth_hint_count << ","
        << "\"cloth_runtime_schema\":1,"
        << "\"cloth_batch_count\":" << state.cloth_runtime_batch_count << ","
        << "\"cloth_particle_count\":" << state.cloth_runtime_particle_count << ","
        << "\"cloth_constraint_count\":" << state.cloth_runtime_constraint_count << ","
        << "\"cloth_collider_file\":\"\","
        << "\"cloth_collider_count\":0,"
        << "\"batches\":[" << state.batches_json.str() << "]"
        << "}";
    return manifest.str();
}

static NativePackage finish_package_write(PackageWriteState state) {
    state.package.path = state.package_dir;
    state.package.batch_count = state.emitted_batch_count;
    state.package.vertex_count = state.emitted_vertex_count;
    state.package.face_count = state.geometry.face_count;
    add_package_asset_family_rows(state);
    write_text(state.package_dir / "manifest.json", package_manifest_json(state));
    return std::move(state.package);
}
