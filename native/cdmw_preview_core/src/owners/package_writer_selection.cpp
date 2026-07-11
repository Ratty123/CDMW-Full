static void select_package_batch_bindings(PackageWriteState& state, PackageBatchState& batch) {
    const EntryJob& job = state.job;
    const NativeSubmesh& mesh = *batch.mesh;
    batch.base = job_allows_texture_role(job, "base")
        ? best_base_binding_for_mode(
            state.bindings, mesh, job, &batch.base_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.base_low_authority_overlay_selected = base_binding_is_low_authority_overlay(batch.base)
        && !(batch.base != nullptr && binding_is_authoritative_same_family_overlay_base(*batch.base, mesh));
    if (job_allows_texture_role(job, "base")
        && (batch.base == nullptr || batch.base_low_authority_overlay_selected)) {
        const TextureBinding* layer_base = best_visible_layer_base_fallback(
            state.bindings,
            mesh,
            batch.base,
            &batch.visible_layer_albedo_score,
            &state.package.rejected_texture_examples);
        if (layer_base != nullptr
            && (batch.base == nullptr || batch.visible_layer_albedo_score >= batch.base_score - 20
                || batch.base_low_authority_overlay_selected)) {
            batch.base = layer_base;
            batch.base_score = batch.visible_layer_albedo_score;
            batch.visible_layer_albedo_used = true;
            batch.base_low_authority_overlay_selected = false;
            state.package.notes.push_back(
                "native visible layer albedo used: batch " + std::to_string(batch.index)
                + "; selected=" + (batch.base->texture_name.empty()
                    ? basename_from_path(batch.base->archive_path) : batch.base->texture_name));
        }
    }
    batch.normal = job_allows_texture_role(job, "normal")
        ? best_binding_for_role(state.bindings, mesh, "normal", &batch.normal_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.material = job_allows_texture_role(job, "material")
        ? best_binding_for_role(state.bindings, mesh, "material", &batch.material_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.height = job_allows_texture_role(job, "height")
        ? best_binding_for_role(state.bindings, mesh, "height", &batch.height_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.specular = job_allows_texture_role(job, "specular")
        ? best_binding_for_role(state.bindings, mesh, "specular", &batch.specular_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.detail = job_allows_texture_role(job, "detail")
        ? best_binding_for_role(state.bindings, mesh, "detail", &batch.detail_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.emissive = job_allows_texture_role(job, "emissive")
        ? best_binding_for_role(state.bindings, mesh, "emissive", &batch.emissive_score, &state.package.rejected_texture_examples)
        : nullptr;
    batch.base_identity_score = batch.base == nullptr ? 0 : material_identity_match_score(*batch.base, mesh);
    const int largest_dimension = batch.base == nullptr ? 0 : std::max(batch.base->dds_width, batch.base->dds_height);
    batch.base_technical = batch.base != nullptr
        && (technical_for_visible_base(batch.base->parameter_name, batch.base->archive_path, batch.base->role)
            || dds_format_is_data_only_for_visible_base(batch.base->dds_format));
    batch.base_semantically_unsafe_skin_albedo = batch.base != nullptr
        && selected_base_is_semantically_unsafe_skin_albedo(*batch.base, mesh);
    const bool authoritative_wrapper = batch.base != nullptr
        && authoritative_wrapper_visible_base_for_mesh(*batch.base, mesh);
    batch.base_low_authority = batch.base != nullptr
        && !authoritative_wrapper
        && !(parameter_is_authoritative_visible_base(batch.base->parameter_name) && batch.base_identity_score >= 120)
        && base_binding_is_low_authority_overlay(batch.base);
    const bool layer_visible = batch.base != nullptr && batch.base->visible_class == "layer_visible";
    const bool authoritative_small_slot = batch.base != nullptr
        && parameter_is_authoritative_visible_base(batch.base->parameter_name)
        && batch.base_identity_score >= 300;
    batch.base_low_res = batch.base != nullptr && largest_dimension > 0 && largest_dimension < 512
        && !batch.base_low_authority && !layer_visible && !authoritative_small_slot;
    batch.base_low_confidence = batch.base != nullptr
        && batch.base_score < 120 && batch.base_identity_score < 72;
    record_base_quality(state, batch);
    batch.bindings = relevant_bindings_for_mesh(
        state.bindings,
        mesh,
        {batch.base, batch.normal, batch.material, batch.height,
         batch.specular, batch.detail, batch.emissive});
}
