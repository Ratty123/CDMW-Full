static std::string surface_profile_json(const SurfaceProfile& profile) {
    std::ostringstream out;
    out << "{"
        << "\"family\":\"" << json_escape(profile.family) << "\","
        << "\"family_code\":" << profile.family_code << ","
        << "\"finish\":\"" << json_escape(profile.finish) << "\","
        << "\"structure\":\"" << json_escape(profile.structure) << "\","
        << "\"coating\":\"" << json_escape(profile.coating) << "\","
        << "\"confidence\":" << profile.confidence << ","
        << "\"evidence\":\"" << json_escape(profile.evidence) << "\","
        << "\"fallbacks\":{"
        << "\"roughness\":" << profile.fallback_roughness << ","
        << "\"metalness\":" << profile.fallback_metalness << ","
        << "\"specular\":" << profile.fallback_specular << ","
        << "\"height_scale\":" << profile.fallback_height_scale << ","
        << "\"anisotropy\":" << profile.fallback_anisotropy << "},"
        << "\"authored\":{"
        << "\"roughness\":" << (profile.roughness_authored ? "true" : "false") << ","
        << "\"metalness\":" << (profile.metalness_authored ? "true" : "false") << ","
        << "\"specular\":" << (profile.specular_authored ? "true" : "false") << ","
        << "\"height_scale\":" << (profile.height_scale_authored ? "true" : "false") << ","
        << "\"anisotropy\":" << (profile.anisotropy_authored ? "true" : "false") << "},"
        << "\"fallback_applied\":{"
        << "\"roughness\":" << (profile.roughness_fallback_applied ? "true" : "false") << ","
        << "\"metalness\":" << (profile.metalness_fallback_applied ? "true" : "false") << ","
        << "\"specular\":" << (profile.specular_fallback_applied ? "true" : "false") << ","
        << "\"height_scale\":" << (profile.height_scale_fallback_applied ? "true" : "false") << ","
        << "\"anisotropy\":" << (profile.anisotropy_fallback_applied ? "true" : "false") << "}"
        << "}";
    return out.str();
}

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
        << "\"surface_profile\":" << surface_profile_json(batch.surface_profile) << ","
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
        << "\"surface_profile\":" << surface_profile_json(batch.surface_profile) << ","
        << "\"uv_flip_policy\":\"legacy_no_flip\","
        << "\"normal_y_policy\":\"shader_invert_legacy_compat\","
        << "\"evidence_grade\":\"" << json_escape(
            batch.material_layers.empty() ? "approximate" : batch.material_layers.front().evidence_grade) << "\""
        << "}";
}

static void append_material_parameter_records_json(
    std::ostringstream& out,
    const std::vector<MaterialParameterRecord>& parameters
) {
    out << "\"material_parameters\":[";
    bool first = true;
    for (const MaterialParameterRecord& parameter : parameters) {
        if (!first) out << ",";
        first = false;
        out << "{"
            << "\"parameter_kind\":\"" << json_escape(parameter.kind) << "\","
            << "\"parameter_name\":\"" << json_escape(parameter.name) << "\","
            << "\"tag_name\":\"" << json_escape(parameter.tag_name) << "\","
            << "\"string_item_id\":\"" << json_escape(parameter.string_item_id) << "\","
            << "\"item_id\":\"" << json_escape(parameter.item_id) << "\","
            << "\"index\":" << parameter.index << ","
            << "\"value\":\"" << json_escape(parameter.value) << "\","
            << "\"texture_path\":\"" << json_escape(parameter.texture_path) << "\","
            << "\"color_value\":[";
        if (parameter.kind == "color") {
            const std::array<float, 4> color = color_parameter_value(parameter.value);
            out << color[0] << "," << color[1] << "," << color[2];
        }
        out << "],\"numeric_value\":";
        if (parameter.has_numeric) out << parameter.numeric_value;
        else out << "null";
        out << ",\"integer_value\":";
        if (parameter.has_integer) out << parameter.integer_value;
        else out << "null";
        out << "}";
    }
    out << "]";
}

static bool package_binding_is_conserved_logical_texture_edge(
    const PackageWriteState& state,
    const TextureBinding& binding
) {
    const std::string binding_scope = lower_copy(binding.component_scope_id);
    const std::string binding_owner = lower_copy(binding.owner_wrapper_item_id);
    const std::string binding_parameter = lower_copy(binding.parameter_name);
    const std::string binding_path = lower_copy(
        native_archive_path(binding.declared_texture_path));
    for (const NativeMaterialConservationRow& row : state.package.material_conservation_rows) {
        if (!row.logical_graph_edge || row.parameter.kind != "texture"
            || row.parameter.texture_path.empty()) continue;
        if (lower_copy(row.component_scope_id) != binding_scope
            || lower_copy(row.owner_wrapper_item_id) != binding_owner
            || row.material_wrapper_index != binding.material_wrapper_index
            || lower_copy(row.parameter.name) != binding_parameter
            || lower_copy(native_archive_path(row.parameter.texture_path)) != binding_path) {
            continue;
        }
        return true;
    }
    return false;
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
        const TextureBinding& binding = *binding_ptr;
        // Embedded mesh-name lookups are renderer slot candidates, not PAC
        // material-parameter edges. They stay in the role slots above and must
        // not masquerade as conserved sidecar material inputs.
        if (binding.source_authority == "embedded_mesh") continue;
        if (batch.base_tint_only_fallback && binding_ptr == batch.base) continue;
        // Suffix-derived companion maps can still drive selected renderer slots
        // and compiled material layers, but `material_inputs` is the auditable
        // PAC edge inventory. Publish only exact component/owner/wrapper/
        // parameter/path identities already recorded by conservation.
        if (!package_binding_is_conserved_logical_texture_edge(state, binding)) continue;
        if (!job_allows_texture_role(state.job, binding.role)) continue;
        const int owner_slot_index = state.binding_owner_slots.at(&binding);
        if (!first) state.batches_json << ",";
        first = false;
        state.batches_json << "{"
            << "\"slot\":\"" << json_escape(binding.role) << "\","
            << "\"source_path\":\"" << json_escape(binding.source_path) << "\","
            << "\"archive_path\":\"" << json_escape(binding.archive_path) << "\","
            << "\"parameter_name\":\"" << json_escape(binding.parameter_name) << "\","
            << "\"declared_texture_path\":\"" << json_escape(binding.declared_texture_path) << "\","
            << "\"source_resolution\":\"" << json_escape(binding.source_resolution) << "\","
            << "\"source_resolution_detail\":\"" << json_escape(binding.source_resolution_detail) << "\","
            << "\"declared_source_missing\":" << (binding.declared_source_missing ? "true" : "false") << ","
            << "\"logical_graph_edge\":true,"
            << "\"semantic_type\":\"" << json_escape(binding.semantic_type) << "\","
            << "\"semantic_subtype\":\"" << json_escape(binding.semantic_subtype) << "\","
            << "\"material_name\":\"" << json_escape(binding.material_name) << "\","
            << "\"owner_wrapper_item_id\":\"" << json_escape(binding.owner_wrapper_item_id) << "\","
            << "\"shader_family\":\"" << json_escape(binding.shader_family) << "\","
            << "\"shader_rule\":\"" << json_escape(binding.shader_rule) << "\","
            << "\"sidecar_path\":\"" << json_escape(binding.sidecar_path) << "\","
            << "\"component_scope_id\":\"" << json_escape(binding.component_scope_id) << "\","
            << "\"representation_sidecar_paths\":[";
        for (size_t representation_index = 0;
             representation_index < binding.representation_sidecar_paths.size();
             ++representation_index) {
            if (representation_index) state.batches_json << ",";
            state.batches_json << "\"" << json_escape(
                binding.representation_sidecar_paths[representation_index]) << "\"";
        }
        state.batches_json << "],"
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
            << "\"detail_scale\":" << binding.detail_scale << ","
            << "\"roughness_hint\":" << binding.roughness_hint << ","
            << "\"metalness_hint\":" << binding.metalness_hint << ","
            << "\"specular_hint\":" << binding.specular_hint << ","
            << "\"height_scale_hint\":" << binding.height_scale_hint << ","
            << "\"emissive_intensity_hint\":" << binding.emissive_intensity_hint << ","
            << "\"tint_color\":[" << binding.tint_color[0] << "," << binding.tint_color[1]
            << "," << binding.tint_color[2] << "," << binding.tint_color[3] << "],"
            << "\"blend_flags\":\"" << json_escape(binding.blend_flags) << "\","
            << "\"material_parameter_names\":\"" << json_escape(binding.material_parameter_names) << "\","
            ;
        append_material_parameter_records_json(state.batches_json, binding.material_parameters);
        state.batches_json << ","
            << "\"alpha_test_enabled\":" << (binding.alpha_test_enabled ? "true" : "false") << ","
            << "\"pbd_simulation_material\":\"" << json_escape(binding.pbd_simulation_material_name) << "\","
            << "\"pbd_simulation_kind\":\"" << json_escape(binding.pbd_simulation_kind) << "\","
            << "\"pbd_material_name\":\"" << json_escape(binding.pbd_material_name) << "\","
            << "\"pbd_submesh_name\":\"" << json_escape(binding.pbd_submesh_name) << "\","
            << "\"visible_class\":\"" << json_escape(binding.visible_class) << "\","
            << "\"source_authority\":\"" << json_escape(binding.source_authority) << "\","
            << "\"owner_slot_index\":" << owner_slot_index << ","
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
        << ",\"component_scope_id\":\"" << json_escape(
            material_component_scope_id_for_mesh(mesh)) << "\""
        << ",\"source_component_label\":\"" << json_escape(mesh.source_component_label) << "\""
        << ",\"prefab_component\":" << (mesh.source_prefab_component ? "true" : "false")
        << ",\"context_component\":" << (mesh.source_context_component ? "true" : "false")
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
        << ",\"roughness_authored\":" << (batch.effective_material_hints.roughness_authored ? "true" : "false")
        << ",\"metalness_authored\":" << (batch.effective_material_hints.metalness_authored ? "true" : "false")
        << ",\"specular_authored\":" << (batch.effective_material_hints.specular_authored ? "true" : "false")
        << ",\"height_scale_authored\":" << (batch.effective_material_hints.height_scale_authored ? "true" : "false")
        << ",\"source\":\"native_core_surface_profile\"},"
        << "\"material_category\":\"" << json_escape(batch.material_category) << "\","
        << "\"material_category_confidence\":" << batch.material_category_confidence << ","
        << "\"material_category_reason\":\"" << json_escape(batch.material_category_reason) << "\","
        << "\"surface_profile\":" << surface_profile_json(batch.surface_profile) << ","
        << "\"roughness_hint_present\":" << (batch.effective_material_hints.roughness_authored ? "true" : "false") << ","
        << "\"metalness_hint_present\":" << (batch.effective_material_hints.metalness_authored ? "true" : "false") << ","
        << "\"specular_hint_present\":" << (batch.effective_material_hints.specular_authored ? "true" : "false") << ","
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
