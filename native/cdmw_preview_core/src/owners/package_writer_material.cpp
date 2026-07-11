static void prepare_package_batch_runtime(PackageWriteState& state, PackageBatchState& batch) {
    const NativeSubmesh& mesh = *batch.mesh;
    batch.cloth_runtime = build_native_cloth_runtime_batch(
        state.job,
        *state.package_index,
        state.submeshes,
        batch.index,
        mesh,
        batch.bindings,
        state.package_dir,
        state.geometry_dir,
        batch.stem,
        state.geometry.center,
        state.geometry.scale);
    if (batch.cloth_runtime.active) {
        ++state.cloth_runtime_batch_count;
        state.cloth_runtime_particle_count += batch.cloth_runtime.particle_count;
        state.cloth_runtime_constraint_count += batch.cloth_runtime.constraint_count;
        state.package.notes.push_back(
            "native tool-side PBD physics runtime: batch " + std::to_string(batch.index)
            + "; material=" + batch.cloth_runtime.hint.simulation_material_name
            + "; particles=" + std::to_string(batch.cloth_runtime.particle_count)
            + "; constraints=" + std::to_string(batch.cloth_runtime.constraint_count));
    }
    const std::string alpha_part_text = lower_copy(
        mesh.material + " " + mesh.name + " "
        + (batch.base == nullptr ? std::string() : batch.base->texture_name + " " + batch.base->archive_path));
    batch.is_eye_surface = evidence_contains_eye_cutout_surface_token(alpha_part_text);
    batch.is_hair = evidence_contains_token(alpha_part_text, "hair")
        || evidence_contains_token(alpha_part_text, "fur")
        || evidence_contains_token(alpha_part_text, "beard")
        || evidence_contains_token(alpha_part_text, "brow")
        || evidence_contains_token(alpha_part_text, "eyebrow")
        || evidence_contains_token(alpha_part_text, "lash")
        || evidence_contains_token(alpha_part_text, "eyelash");
    for (const TextureBinding* binding : batch.bindings) {
        if (binding == nullptr) continue;
        const std::string rule = lower_copy(
            binding->shader_rule + " " + binding->shader_family + " " + binding->material_parameter_names);
        if (rule.find("hair") != std::string::npos || rule.find("fur") != std::string::npos) batch.is_hair = true;
        if (binding->alpha_test_enabled
            || rule.find("alphatest") != std::string::npos
            || rule.find("alphaclip") != std::string::npos
            || rule.find("alphacutout") != std::string::npos
            || rule.find("cutout") != std::string::npos) batch.has_alpha_test = true;
    }
    batch.uses_alpha_cutout = batch.is_hair || batch.is_eye_surface || batch.has_alpha_test;
    batch.alpha_threshold = batch.is_hair ? 0.18f
        : (batch.is_eye_surface ? 0.05f : (batch.has_alpha_test ? 0.08f : 0.0f));
    batch.material_hints = material_hints_for_bindings(batch.bindings);
    if (batch.base != nullptr) return;
    for (const TextureBinding* binding : batch.bindings) {
        if (binding == nullptr) continue;
        const auto tint = binding->tint_color;
        const bool has_tint = std::abs(tint[0] - 1.0f) > 0.02f
            || std::abs(tint[1] - 1.0f) > 0.02f
            || std::abs(tint[2] - 1.0f) > 0.02f;
        if (!has_tint) continue;
        batch.color = {
            std::clamp(tint[0], 0.05f, 1.0f),
            std::clamp(tint[1], 0.05f, 1.0f),
            std::clamp(tint[2], 0.05f, 1.0f),
        };
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material
            + ": native material tint fallback used because no true base DDS was selected");
        break;
    }
}

static void prepare_package_batch_material(PackageWriteState& state, PackageBatchState& batch) {
    const NativeSubmesh& mesh = *batch.mesh;
    batch.held_layer_albedo = shader_rule_holds_layer_albedo(batch.bindings);
    if (!batch.held_layer_albedo && batch.visible_layer_albedo_used
        && binding_is_tintable_visible_layer_base(batch.base)
        && tint_color_is_visible(batch.base->tint_color)) {
        batch.color = preview_tint_rgb_for_binding(batch.base);
        batch.visible_layer_tint_applied = true;
        batch.visible_layer_tint_color = batch.base->tint_color;
        state.package.notes.push_back(
            "native visible layer tint applied: batch " + std::to_string(batch.index)
            + "; tint=[" + std::to_string(batch.color[0]) + ","
            + std::to_string(batch.color[1]) + "," + std::to_string(batch.color[2]) + "]");
    }
    batch.material_layers = compile_material_layers(
        batch.bindings,
        mesh,
        batch.base,
        batch.normal,
        batch.material,
        batch.height,
        batch.specular,
        batch.material_hints,
        state.job.visible_texture_mode);
    if (!batch.held_layer_albedo && !batch.visible_layer_tint_applied) {
        std::array<float, 4> sidecar_tint{1.0f, 1.0f, 1.0f, 1.0f};
        if (preview_sidecar_tint_for_surface(batch.base, mesh, batch.material_layers, &sidecar_tint)) {
            batch.color = preview_tint_rgb_for_color(sidecar_tint);
            batch.visible_layer_tint_applied = true;
            batch.visible_layer_tint_color = sidecar_tint;
            state.package.notes.push_back(
                "native sidecar tint applied: batch " + std::to_string(batch.index)
                + "; tint=[" + std::to_string(batch.color[0]) + ","
                + std::to_string(batch.color[1]) + "," + std::to_string(batch.color[2]) + "]");
        }
    }
    if (batch.visible_layer_tint_applied) {
        filter_material_layers_for_visible_tint(batch.material_layers, batch.visible_layer_tint_color, mesh);
    }
    batch.material_category = material_category_for_bindings(
        batch.bindings, mesh, batch.base, batch.material_layers);
    batch.material_category_reason = material_category_reason_for_bindings(
        batch.material_category, batch.bindings, mesh, batch.base, batch.material_layers);
    batch.material_category_confidence = material_category_confidence(
        batch.material_category, batch.bindings, batch.base);
    batch.effective_material_hints = clamp_material_hints_for_category(
        batch.material_hints, batch.material_category);
    batch.force_nonmetal_equipment_layer_tint = nonmetal_equipment_texturelayer_base(
        batch.base, mesh, batch.material_category);
    if (nonmetal_equipment_texturelayer_without_tint(
        batch.base, mesh, batch.material_category, batch.visible_layer_tint_applied)) {
        batch.color = fallback_nonmetal_equipment_layer_color(batch.material_category, mesh, batch.base);
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material
            + ": raw equipment texture-layer albedo muted because no visible sidecar tint was decoded");
    }
    batch.material_response_promoted = batch.material_category == "metal"
        && promoted_global_material_response(batch.material);
    batch.material_response = material_response_disposition(
        batch.material, batch.specular, batch.material_category);
    state.has_metal_preview_response = state.has_metal_preview_response
        || (batch.material_category == "metal" && batch.material_category_confidence >= 0.45f);
    const bool strong_metal_response = batch.material_response.find("metal_response") != std::string::npos
        || batch.material_response.find("metallic") != std::string::npos
        || batch.material_response.find("promoted") != std::string::npos;
    batch.metalness_hint = batch.material_category == "metal"
        ? std::max(batch.effective_material_hints.metalness, strong_metal_response ? 0.68f : 0.56f)
        : batch.effective_material_hints.metalness;
    batch.specular_hint = batch.material_category == "metal"
        ? std::max(batch.effective_material_hints.specular, strong_metal_response ? 0.68f : 0.56f)
        : batch.effective_material_hints.specular;
    batch.roughness_hint = batch.material_category == "metal"
        ? std::min(batch.effective_material_hints.roughness, strong_metal_response ? 0.24f : 0.32f)
        : batch.effective_material_hints.roughness;
    batch.base_tint_strength = native_preview_base_tint_strength(
        batch.base, batch.color, batch.material_layers, batch.visible_layer_tint_applied,
        batch.force_nonmetal_equipment_layer_tint);
    batch.preview_emissive = emissive_binding_is_safe_for_preview(
        batch.emissive, mesh, batch.material_category) ? batch.emissive : nullptr;
    if (batch.emissive != nullptr && batch.preview_emissive == nullptr
        && batch.emissive->emissive_intensity_hint > 0.001f) {
        state.package.base_quality_notes.push_back(
            "batch " + std::to_string(batch.index) + " " + mesh.material
            + ": generic emissive/effect texture suppressed for non-emissive material preview");
    }
    for (const MaterialLayer& layer : batch.material_layers) {
        if (layer.layer_role == "base" || layer.diffuse_source.empty()) continue;
        batch.primary_layer = &layer;
        break;
    }
}

static std::string package_texture_label(const TextureBinding* binding) {
    if (binding == nullptr) return "-";
    std::string text = binding->texture_name.empty()
        ? basename_from_path(binding->archive_path) : binding->texture_name;
    const int largest_dimension = std::max(binding->dds_width, binding->dds_height);
    if (largest_dimension > 0) {
        text += " " + std::to_string(binding->dds_width) + "x" + std::to_string(binding->dds_height);
    }
    if (!binding->dds_format.empty()) text += " " + binding->dds_format;
    return text;
}

static void record_package_batch_selection(PackageWriteState& state, const PackageBatchState& batch) {
    if (state.package.selected_texture_examples.size() >= 12) return;
    const NativeSubmesh& mesh = *batch.mesh;
    state.package.selected_texture_examples.push_back(
        "batch " + std::to_string(batch.index) + " " + mesh.material
        + ": base=" + package_texture_label(batch.base)
        + ", normal=" + package_texture_label(batch.normal)
        + ", material=" + package_texture_label(batch.material)
        + ", height=" + package_texture_label(batch.height)
        + ", emissive=" + package_texture_label(batch.preview_emissive)
        + (batch.visible_layer_albedo_used ? ", visible_layer_albedo=used" : "")
        + (batch.visible_layer_tint_applied ? ", visible_layer_tint=applied" : "")
        + (batch.base_low_authority_overlay_selected ? ", base_low_authority_overlay=true" : "")
        + (batch.base_semantically_unsafe_skin_albedo ? ", base_wrong_family_layer=true" : "")
        + ", material_category=" + batch.material_category
        + ", material_category_reason=" + batch.material_category_reason
        + ", material_response=" + batch.material_response
        + ", uv_flip_policy=legacy_no_flip"
        + ", normal_y_policy=shader_invert_legacy_compat");
}
