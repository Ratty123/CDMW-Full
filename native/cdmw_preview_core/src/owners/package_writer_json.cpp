static void append_package_material_slot_and_decision(
    PackageWriteState& state,
    const PackageBatchState& batch
) {
    const NativeSubmesh& mesh = *batch.mesh;
    const TextureBinding* preview_base = package_preview_base(batch);
    if (state.emitted_batch_count > 0) {
        state.material_slots_json << ",";
        state.selection_decisions_json << ",";
    }
    state.material_slots_json << "{"
        << "\"batch_index\":" << batch.index << ","
        << "\"material_name\":\"" << json_escape(mesh.material) << "\","
        << "\"submesh_name\":\"" << json_escape(mesh.name) << "\","
        << "\"shader_family\":\"" << json_escape(batch.bindings.empty() ? "" : batch.bindings.front()->shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(batch.bindings.empty() ? "generic" : batch.bindings.front()->shader_rule) << "\","
        << "\"material_category\":\"" << json_escape(batch.material_category) << "\","
        << "\"material_category_confidence\":" << batch.material_category_confidence << ","
        << "\"material_category_reason\":\"" << json_escape(batch.material_category_reason) << "\","
        << "\"material_response_disposition\":\"" << json_escape(batch.material_response) << "\","
        << "\"base\":\"" << json_escape(preview_base == nullptr ? "" : preview_base->archive_path) << "\","
        << "\"normal\":\"" << json_escape(batch.normal == nullptr ? "" : batch.normal->archive_path) << "\","
        << "\"material\":\"" << json_escape(batch.material == nullptr ? "" : batch.material->archive_path) << "\","
        << "\"specular\":\"" << json_escape(batch.specular == nullptr ? "" : batch.specular->archive_path) << "\","
        << "\"height\":\"" << json_escape(batch.height == nullptr ? "" : batch.height->archive_path) << "\","
        << "\"detail\":\"" << json_escape(batch.detail == nullptr ? "" : batch.detail->archive_path) << "\","
        << "\"emissive\":\"" << json_escape(batch.preview_emissive == nullptr ? "" : batch.preview_emissive->archive_path) << "\""
        << "}";
    state.selection_decisions_json << "{"
        << "\"batch_index\":" << batch.index << ","
        << "\"visible_texture_mode\":\"" << json_escape(state.job.visible_texture_mode) << "\","
        << "\"base_selected\":\"" << json_escape(batch.base == nullptr ? "" : batch.base->archive_path) << "\","
        << "\"base_score\":" << batch.base_score << ","
        << "\"base_identity_score\":" << batch.base_identity_score << ","
        << "\"emissive_selected\":\"" << json_escape(batch.preview_emissive == nullptr ? "" : batch.preview_emissive->archive_path) << "\","
        << "\"emissive_score\":" << batch.emissive_score << ","
        << "\"base_missing\":" << (batch.base == nullptr ? "true" : "false") << ","
        << "\"base_technical\":" << (batch.base_technical ? "true" : "false") << ","
        << "\"base_low_res\":" << (batch.base_low_res ? "true" : "false") << ","
        << "\"base_low_confidence\":" << (batch.base_low_confidence ? "true" : "false") << ","
        << "\"base_low_authority_overlay\":" << (batch.base_low_authority_overlay_selected ? "true" : "false") << ","
        << "\"base_wrong_family_layer\":" << (batch.base_wrong_family_layer ? "true" : "false") << ","
        << "\"base_tint_only_fallback\":" << (batch.base_tint_only_fallback ? "true" : "false") << ","
        << "\"visible_layer_albedo_used\":" << (batch.visible_layer_albedo_used ? "true" : "false") << ","
        << "\"visible_layer_albedo_score\":" << batch.visible_layer_albedo_score << ","
        << "\"visible_layer_tint_applied\":" << (batch.visible_layer_tint_applied ? "true" : "false") << ","
        << "\"visible_layer_tint_color\":[" << batch.visible_layer_tint_color[0] << ","
        << batch.visible_layer_tint_color[1] << "," << batch.visible_layer_tint_color[2] << ","
        << batch.visible_layer_tint_color[3] << "],"
        << "\"material_category_reason\":\"" << json_escape(batch.material_category_reason) << "\","
        << "\"uv_flip_policy\":\"legacy_no_flip\","
        << "\"normal_y_policy\":\"shader_invert_legacy_compat\","
        << "\"evidence_grade\":\"" << json_escape(
            batch.material_layers.empty() ? "approximate" : batch.material_layers.front().evidence_grade) << "\""
        << "}";
}

static void append_package_material_inputs(
    PackageWriteState& state,
    const PackageBatchState& batch
) {
    const TextureBinding* preview_base = package_preview_base(batch);
    bool wrote_slot = false;
    for (const auto& slot : std::vector<std::pair<std::string, const TextureBinding*>>{
        {"base", preview_base},
        {"normal", batch.normal},
        {"material", batch.material},
        {"height", batch.height},
        {"emissive", batch.preview_emissive},
    }) {
        if (!job_allows_texture_role(state.job, slot.first)) continue;
        const std::string slot_json = dds_entry_json(slot.second, slot.first);
        if (slot_json.empty()) continue;
        if (wrote_slot) state.batches_json << ",";
        state.batches_json << slot_json;
        wrote_slot = true;
    }
    if (batch.bindings.empty()) return;
    if (wrote_slot) state.batches_json << ",";
    state.batches_json << "\"material_inputs\":[";
    bool first = true;
    for (const TextureBinding* binding_ptr : batch.bindings) {
        if (binding_ptr == nullptr || binding_ptr->source_path.empty()) continue;
        if (batch.base_tint_only_fallback && binding_ptr == batch.base) continue;
        const TextureBinding& binding = *binding_ptr;
        if (!job_allows_texture_role(state.job, binding.role)) continue;
        if (!first) state.batches_json << ",";
        first = false;
        state.batches_json << "{"
            << "\"slot\":\"" << json_escape(binding.role) << "\","
            << "\"source_path\":\"" << json_escape(binding.source_path) << "\","
            << "\"archive_path\":\"" << json_escape(binding.archive_path) << "\","
            << "\"parameter_name\":\"" << json_escape(binding.parameter_name) << "\","
            << "\"semantic_type\":\"" << json_escape(binding.semantic_type) << "\","
            << "\"semantic_subtype\":\"" << json_escape(binding.semantic_subtype) << "\","
            << "\"material_name\":\"" << json_escape(binding.material_name) << "\","
            << "\"shader_family\":\"" << json_escape(binding.shader_family) << "\","
            << "\"shader_rule\":\"" << json_escape(binding.shader_rule) << "\","
            << "\"sidecar_path\":\"" << json_escape(binding.sidecar_path) << "\","
            << "\"sidecar_kind\":\"" << json_escape(binding.sidecar_kind) << "\","
            << "\"linked_mesh_path\":\"" << json_escape(binding.linked_mesh_path) << "\","
            << "\"packed_channels\":\"" << json_escape(binding.packed_channels) << "\","
            << "\"srgb_mode\":\"" << json_escape(binding.srgb_mode) << "\","
            << "\"parameter_declared_by\":\"" << json_escape(binding.parameter_declared_by) << "\","
            << "\"material_output_quality\":\"" << json_escape(binding.material_output_quality) << "\","
            << "\"evidence_grade\":\"" << json_escape(binding.evidence_grade) << "\","
            << "\"layer_role\":\"" << json_escape(binding.layer_role) << "\","
            << "\"layer_channel\":\"" << json_escape(binding.layer_channel) << "\","
            << "\"layer_weight\":" << binding.layer_weight << ","
            << "\"roughness_hint\":" << binding.roughness_hint << ","
            << "\"metalness_hint\":" << binding.metalness_hint << ","
            << "\"specular_hint\":" << binding.specular_hint << ","
            << "\"height_scale_hint\":" << binding.height_scale_hint << ","
            << "\"emissive_intensity_hint\":" << binding.emissive_intensity_hint << ","
            << "\"tint_color\":[" << binding.tint_color[0] << "," << binding.tint_color[1]
            << "," << binding.tint_color[2] << "," << binding.tint_color[3] << "],"
            << "\"blend_flags\":\"" << json_escape(binding.blend_flags) << "\","
            << "\"material_parameter_names\":\"" << json_escape(binding.material_parameter_names) << "\","
            << "\"alpha_test_enabled\":" << (binding.alpha_test_enabled ? "true" : "false") << ","
            << "\"pbd_simulation_material\":\"" << json_escape(binding.pbd_simulation_material_name) << "\","
            << "\"pbd_simulation_kind\":\"" << json_escape(binding.pbd_simulation_kind) << "\","
            << "\"pbd_material_name\":\"" << json_escape(binding.pbd_material_name) << "\","
            << "\"pbd_submesh_name\":\"" << json_escape(binding.pbd_submesh_name) << "\","
            << "\"visible_class\":\"" << json_escape(binding.visible_class) << "\","
            << "\"source_authority\":\"" << json_escape(binding.source_authority) << "\","
            << "\"material_wrapper_index\":" << binding.material_wrapper_index << ","
            << "\"material_wrapper_count\":" << binding.material_wrapper_count << ","
            << "\"material_wrapper_order_authoritative\":" << (binding.material_wrapper_order_authoritative ? "true" : "false") << ","
            << "\"mesh_identity_score\":" << material_identity_match_score(binding, *batch.mesh) << ","
            << "\"relation_confidence\":\"" << json_escape(binding.relation_confidence) << "\","
            << "\"relation_reason\":\"" << json_escape(binding.relation_reason) << "\","
            << "\"width\":" << binding.dds_width << ","
            << "\"height\":" << binding.dds_height << ","
            << "\"format\":\"" << json_escape(binding.dds_format) << "\","
            << "\"available\":true,"
            << "\"direct_upload_candidate\":true"
            << "}";
    }
    state.batches_json << "]";
}

static void append_package_batch_json_head(PackageWriteState& state, const PackageBatchState& batch) {
    const NativeSubmesh& mesh = *batch.mesh;
    if (state.emitted_batch_count++) state.batches_json << ",";
    state.batches_json << "{"
        << "\"index\":" << batch.index << ","
        << "\"material_name\":\"" << json_escape(mesh.material) << "\","
        << "\"texture_name\":\"" << json_escape(mesh.material.empty() ? mesh.name : mesh.material) << "\","
        << "\"vertex_file\":\"" << json_escape(batch.geometry_path.lexically_relative(state.package_dir).generic_string()) << "\","
        << "\"vertex_count\":" << batch.vertex_count << ","
        << "\"editor_identity\":{\"source_submesh_index\":" << mesh.source_submesh_index
        << ",\"source_local_submesh_index\":" << mesh.source_local_submesh_index
        << ",\"source_component_index\":" << mesh.source_component_index
        << ",\"source_model_path\":\"" << json_escape(mesh.source_model_path) << "\""
        << ",\"source_component_label\":\"" << json_escape(mesh.source_component_label) << "\""
        << ",\"prefab_component\":" << (mesh.source_prefab_component ? "true" : "false")
        << ",\"part_label\":\"" << json_escape(mesh.source_component_label.empty() ? mesh.material : mesh.source_component_label) << "\""
        << ",\"identity_file\":\"" << json_escape(batch.identity_path.lexically_relative(state.package_dir).generic_string()) << "\"},"
        << "\"base_color\":[" << batch.color[0] << "," << batch.color[1] << "," << batch.color[2] << "],"
        << "\"roughness\":" << batch.roughness_hint << ","
        << "\"metalness\":" << batch.metalness_hint << ","
        << "\"specular\":" << batch.specular_hint << ","
        << "\"height_scale\":" << batch.effective_material_hints.height_scale << ","
        << "\"native_material_hints\":{\"roughness\":" << batch.roughness_hint
        << ",\"metalness\":" << batch.metalness_hint
        << ",\"specular\":" << batch.specular_hint
        << ",\"height_scale\":" << batch.effective_material_hints.height_scale
        << ",\"source\":\"native_core_material_category\"},"
        << "\"material_category\":\"" << json_escape(batch.material_category) << "\","
        << "\"material_category_confidence\":" << batch.material_category_confidence << ","
        << "\"material_category_reason\":\"" << json_escape(batch.material_category_reason) << "\","
        << "\"material_response_promoted\":" << (batch.material_response_promoted ? "true" : "false") << ","
        << "\"material_response_disposition\":\"" << json_escape(batch.material_response) << "\","
        << "\"base_tint_strength\":" << batch.base_tint_strength << ","
        << "\"emissive_intensity\":" << (batch.preview_emissive == nullptr ? 0.0f : batch.preview_emissive->emissive_intensity_hint) << ","
        // The emissive colour comes from the source: an authored emissive colour
        // parameter if the material declares one, otherwise neutral so the `_emi`
        // map's own colour is what shows. This was a fixed cyan, which reported
        // the same glow colour for greek fire, a lightning thrower and an ancient
        // giant's runes -- every emissive surface in the game, tinted blue.
        << "\"emissive_color\":["
        << (batch.preview_emissive == nullptr ? 1.0f : batch.preview_emissive->emissive_color[0]) << ","
        << (batch.preview_emissive == nullptr ? 1.0f : batch.preview_emissive->emissive_color[1]) << ","
        << (batch.preview_emissive == nullptr ? 1.0f : batch.preview_emissive->emissive_color[2]) << "],"
        << "\"textures\":{},"
        << "\"dds_textures\":{";
    append_package_material_inputs(state, batch);
    state.batches_json << "},";
}
