static void append_package_batch_runtime_json(PackageWriteState& state, const PackageBatchState& batch) {
    const NativeSubmesh& mesh = *batch.mesh;
    const NativeClothRuntimeBatch& cloth = batch.cloth_runtime;
    state.batches_json
        << "\"texture_flip_vertical\":" << (state.job.flip_texture_v ? "true" : "false") << ","
        << "\"uv_flip_policy\":\"" << (state.job.flip_texture_v ? "user_flip_v" : "legacy_no_flip") << "\","
        << "\"normal_y_policy\":\"shader_invert_legacy_compat\","
        << "\"alpha_mode\":\"" << (batch.uses_alpha_cutout ? "alpha_cutout" : "opaque") << "\","
        << "\"alpha_threshold\":" << batch.alpha_threshold << ","
        << "\"two_sided\":" << ((batch.is_hair || batch.is_eye_surface) ? "true" : "false") << ","
        << "\"cloth_enabled\":" << (cloth.active ? "true" : "false") << ","
        << "\"cloth_kind\":\"" << json_escape(cloth.active ? cloth.settings.simulation_kind : "") << "\","
        << "\"cloth_material_name\":\"" << json_escape(cloth.active ? cloth.hint.simulation_material_name : "") << "\","
        << "\"cloth_particle_file\":\"" << json_escape(cloth.active ? cloth.particle_path.lexically_relative(state.package_dir).generic_string() : "") << "\","
        << "\"cloth_pin_file\":\"" << json_escape(cloth.active ? cloth.pin_path.lexically_relative(state.package_dir).generic_string() : "") << "\","
        << "\"cloth_constraint_file\":\"" << json_escape(cloth.active ? cloth.constraint_path.lexically_relative(state.package_dir).generic_string() : "") << "\","
        << "\"cloth_particle_count\":" << (cloth.active ? cloth.particle_count : 0) << ","
        << "\"cloth_constraint_count\":" << (cloth.active ? cloth.constraint_count : 0) << ","
        << "\"cloth_gravity\":" << (cloth.active ? cloth.settings.gravity : -10.0f) << ","
        << "\"cloth_damping\":" << (cloth.active ? cloth.settings.damping : 0.65f) << ","
        << "\"cloth_air_resistance\":" << (cloth.active ? cloth.settings.air_resistance : 1.0f) << ","
        << "\"cloth_wind_response\":" << (cloth.active ? cloth.settings.wind_response : 0.4f) << ","
        << "\"cloth_solver_iterations\":" << (cloth.active ? cloth.settings.solver_iterations : 30) << ","
        << "\"cloth_collision_enabled\":false,"
        << "\"geometry_quality\":{"
        << "\"safe\":" << (mesh.geometry_safe ? "true" : "false") << ","
        << "\"layout\":\"" << json_escape(mesh.vertex_layout_name) << "\","
        << "\"stride\":" << mesh.vertex_stride << ","
        << "\"uv_offset\":" << mesh.uv_offset << ","
        << "\"normal_offset\":" << mesh.normal_offset << ","
        << "\"uv_finite_ratio\":" << mesh.uv_finite_ratio << ","
        << "\"uv_span\":[" << mesh.uv_span_u << "," << mesh.uv_span_v << "],"
        << "\"uv_abs_max\":" << mesh.uv_abs_max << ","
        << "\"uv_edge_outlier_ratio\":" << mesh.uv_edge_outlier_ratio << ","
        << "\"uv_degenerate_triangle_ratio\":" << mesh.uv_degenerate_triangle_ratio << ","
        << "\"degenerate_triangle_ratio\":" << mesh.degenerate_triangle_ratio << ","
        << "\"edge_outlier_ratio\":" << mesh.edge_outlier_ratio << ","
        << "\"normal_valid_ratio\":" << mesh.normal_valid_ratio << ","
        << "\"score\":" << mesh.geometry_quality_score << ","
        << "\"note\":\"" << json_escape(mesh.geometry_quality_note) << "\"},"
        << "\"selected_texture_slots\":{"
        << "\"base\":{\"match_score\":" << batch.base_score << ",\"identity_score\":" << batch.base_identity_score << ",\"archive_path\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->archive_path) << "\"},"
        << "\"normal\":{\"match_score\":" << batch.normal_score << ",\"identity_score\":" << (batch.normal == nullptr ? 0 : material_identity_match_score(*batch.normal, mesh)) << ",\"archive_path\":\"" << json_escape(batch.normal == nullptr ? "" : batch.normal->archive_path) << "\"},"
        << "\"material\":{\"match_score\":" << batch.material_score << ",\"identity_score\":" << (batch.material == nullptr ? 0 : material_identity_match_score(*batch.material, mesh)) << ",\"archive_path\":\"" << json_escape(batch.material == nullptr ? "" : batch.material->archive_path) << "\"},"
        << "\"specular\":{\"match_score\":" << batch.specular_score << ",\"identity_score\":" << (batch.specular == nullptr ? 0 : material_identity_match_score(*batch.specular, mesh)) << ",\"archive_path\":\"" << json_escape(batch.specular == nullptr ? "" : batch.specular->archive_path) << "\"},"
        << "\"height\":{\"match_score\":" << batch.height_score << ",\"identity_score\":" << (batch.height == nullptr ? 0 : material_identity_match_score(*batch.height, mesh)) << ",\"archive_path\":\"" << json_escape(batch.height == nullptr ? "" : batch.height->archive_path) << "\"},"
        << "\"detail\":{\"match_score\":" << batch.detail_score << ",\"identity_score\":" << (batch.detail == nullptr ? 0 : material_identity_match_score(*batch.detail, mesh)) << ",\"archive_path\":\"" << json_escape(batch.detail == nullptr ? "" : batch.detail->archive_path) << "\"}"
        << "},"
        << "\"has_texture_coordinates\":true,"
        << "\"tangents_usable\":true,"
        << "\"shader_family\":\"" << json_escape(batch.bindings.empty() ? "" : batch.bindings.front()->shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(batch.bindings.empty() ? "generic" : batch.bindings.front()->shader_rule) << "\","
        << "\"evidence_grade\":\"" << json_escape(batch.material_layers.empty() ? "approximate" : batch.material_layers.front().evidence_grade) << "\","
        << "\"base_low_authority_overlay\":" << (batch.base_low_authority_overlay_selected ? "true" : "false") << ","
        << "\"visible_layer_albedo_used\":" << (batch.visible_layer_albedo_used ? "true" : "false") << ","
        << "\"visible_layer_albedo_score\":" << batch.visible_layer_albedo_score << ","
        << "\"visible_layer_tint_applied\":" << (batch.visible_layer_tint_applied ? "true" : "false") << ",";
}

static void append_package_batch_material_json(PackageWriteState& state, const PackageBatchState& batch) {
    const NativeSubmesh& mesh = *batch.mesh;
    const MaterialLayer* primary = batch.primary_layer;
    state.batches_json
        << "\"visible_layer_tint_color\":[" << batch.visible_layer_tint_color[0] << ","
        << batch.visible_layer_tint_color[1] << "," << batch.visible_layer_tint_color[2] << ","
        << batch.visible_layer_tint_color[3] << "],"
        << "\"material_layer_count\":" << (batch.material_layers.empty()
            ? 0 : std::max<int>(0, static_cast<int>(batch.material_layers.size()) - 1)) << ","
        << "\"material_layers\":[";
    for (size_t index = 0; index < batch.material_layers.size(); ++index) {
        if (index) state.batches_json << ",";
        state.batches_json << material_layer_json(batch.material_layers[index]);
    }
    state.batches_json << "],"
        << "\"primary_material_layer\":{"
        << "\"active\":" << (primary != nullptr ? "true" : "false") << ","
        << "\"layer_role\":\"" << json_escape(primary == nullptr ? "" : primary->layer_role) << "\","
        << "\"mask_channel\":\"" << json_escape(primary == nullptr ? "r" : primary->layer_channel) << "\","
        << "\"weight\":" << (primary == nullptr ? 0.0f : primary->weight) << ","
        << "\"diffuse_source\":\"" << json_escape(primary == nullptr ? "" : primary->diffuse_source) << "\","
        << "\"mask_source\":\"" << json_escape(primary == nullptr ? "" : primary->mask_source) << "\","
        << "\"material_source\":\"" << json_escape(primary == nullptr ? "" : primary->material_source) << "\","
        << "\"normal_source\":\"" << json_escape(primary == nullptr ? "" : primary->normal_source) << "\","
        << "\"height_source\":\"" << json_escape(primary == nullptr ? "" : primary->height_source) << "\","
        << "\"tint\":[" << (primary == nullptr ? 1.0f : primary->tint[0]) << ","
        << (primary == nullptr ? 1.0f : primary->tint[1]) << ","
        << (primary == nullptr ? 1.0f : primary->tint[2]) << ","
        << (primary == nullptr ? 1.0f : primary->tint[3]) << "],"
        << "\"roughness_hint\":" << (primary == nullptr ? 0.0f : primary->roughness_hint) << ","
        << "\"metalness_hint\":" << (primary == nullptr ? 0.0f : primary->metalness_hint) << ","
        << "\"specular_hint\":" << (primary == nullptr ? 0.0f : primary->specular_hint) << ","
        << "\"height_scale_hint\":" << (primary == nullptr ? 0.0f : primary->height_scale_hint)
        << "},\"unknown_parameters\":[";
    std::set<std::string> unknown_parameters;
    for (const TextureBinding* binding : batch.bindings) {
        if (binding == nullptr) continue;
        if (binding->role == "base" || binding->role == "normal" || binding->role == "height"
            || binding->role == "material" || binding->role == "specular" || binding->role == "detail") continue;
        if (!binding->parameter_name.empty()) unknown_parameters.insert(binding->parameter_name);
    }
    bool first = true;
    for (const std::string& name : unknown_parameters) {
        if (!first) state.batches_json << ",";
        first = false;
        state.batches_json << "\"" << json_escape(name) << "\"";
    }
    state.batches_json << "],\"rejected_inputs\":[";
    first = true;
    for (const TextureBinding* binding : batch.bindings) {
        if (binding == nullptr || binding->role != "base"
            || !technical_for_visible_base(binding->parameter_name, binding->archive_path, binding->role)) continue;
        if (!first) state.batches_json << ",";
        first = false;
        state.batches_json << "{\"parameter_name\":\"" << json_escape(binding->parameter_name)
            << "\",\"archive_path\":\"" << json_escape(binding->archive_path)
            << "\",\"reason\":\"technical map rejected as albedo\"}";
    }
    state.batches_json << "],"
        << "\"native_base_quality\":{\"safe\":" << ((!state.job.use_textures
            || (batch.base != nullptr && !batch.base_technical && !batch.base_semantically_unsafe_skin_albedo
                && !batch.base_low_res && !batch.base_low_confidence && !batch.base_low_authority)) ? "true" : "false")
        << ",\"score\":" << batch.base_score
        << ",\"identity_score\":" << batch.base_identity_score
        << ",\"low_res\":" << (batch.base_low_res ? "true" : "false")
        << ",\"low_authority\":" << (batch.base_low_authority ? "true" : "false")
        << ",\"low_authority_overlay\":" << (batch.base_low_authority_overlay_selected ? "true" : "false")
        << ",\"wrong_family_layer\":" << (batch.base_semantically_unsafe_skin_albedo ? "true" : "false")
        << ",\"visible_layer_albedo_used\":" << (batch.visible_layer_albedo_used ? "true" : "false")
        << ",\"visible_layer_tint_applied\":" << (batch.visible_layer_tint_applied ? "true" : "false")
        << ",\"visible_layer_tint_color\":[" << batch.visible_layer_tint_color[0] << ","
        << batch.visible_layer_tint_color[1] << "," << batch.visible_layer_tint_color[2] << ","
        << batch.visible_layer_tint_color[3] << "]"
        << ",\"technical\":" << (batch.base_technical ? "true" : "false")
        << ",\"missing\":" << (batch.base == nullptr ? "true" : "false")
        << ",\"visible_class\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->visible_class) << "\""
        << ",\"source_authority\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->source_authority) << "\""
        << ",\"source\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->source_path) << "\""
        << ",\"archive_path\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->archive_path) << "\""
        << ",\"texture_name\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->texture_name) << "\""
        << ",\"width\":" << (batch.base == nullptr ? 0 : batch.base->dds_width)
        << ",\"height\":" << (batch.base == nullptr ? 0 : batch.base->dds_height)
        << ",\"format\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->dds_format) << "\"},"
        << "\"normal_strength\":" << state.job.normal_strength_cap << ","
        << "\"height_amount\":" << std::clamp(state.job.height_effect_max * 0.12f, 0.0f, 0.16f) << ","
        << "\"roughness\":" << batch.effective_material_hints.roughness << ","
        << "\"metalness\":" << batch.effective_material_hints.metalness << ","
        << "\"specular\":" << batch.effective_material_hints.specular << ","
        << "\"height_scale\":" << batch.effective_material_hints.height_scale << ","
        << "\"native_material_hints\":{\"shader_family\":\"" << json_escape(batch.bindings.empty() ? "" : batch.bindings.front()->shader_family)
        << "\",\"roughness\":" << batch.effective_material_hints.roughness
        << ",\"metalness\":" << batch.effective_material_hints.metalness
        << ",\"specular\":" << batch.effective_material_hints.specular
        << ",\"height_scale\":" << batch.effective_material_hints.height_scale << "},"
        << "\"notes\":[\"generated by cdmw-preview-core " << json_escape(state.package.mesh_parse)
        << " path\",\"native material inputs scoped to this batch: " << batch.bindings.size() << "\""
        << (batch.held_layer_albedo ? ",\"skin/hair visible layer albedo held until mask semantics are validated\"" : "")
        << (batch.cloth_runtime.active ? ",\"tool-side PBD physics runtime emitted from native material PBD metadata\"" : "")
        << "],"
        << "\"material_combiner_active\":false,"
        << "\"material_combiner_outputs\":[],"
        << "\"material_combiner_decode_modes\":[\"direct_dds_sidecar\"]"
        << "}";
}

static void append_package_batch_json(PackageWriteState& state, const PackageBatchState& batch) {
    append_package_batch_json_head(state, batch);
    append_package_batch_runtime_json(state, batch);
    append_package_batch_material_json(state, batch);
}
