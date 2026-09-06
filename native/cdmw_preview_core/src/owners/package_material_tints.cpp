static std::string material_layer_json(const MaterialLayer& layer) {
    std::ostringstream out;
    out << "{"
        << "\"component_scope_id\":\"" << json_escape(layer.component_scope_id) << "\","
        << "\"owner_wrapper_item_id\":\"" << json_escape(layer.owner_wrapper_item_id) << "\","
        << "\"material_wrapper_index\":" << layer.material_wrapper_index << ","
        << "\"layer_role\":\"" << json_escape(layer.layer_role) << "\","
        << "\"mask_channel\":\"" << json_escape(layer.layer_channel) << "\","
        << "\"shader_family\":\"" << json_escape(layer.shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(layer.shader_rule) << "\","
        << "\"evidence_grade\":\"" << json_escape(layer.evidence_grade) << "\","
        << "\"blend_order\":\"" << json_escape(layer.blend_order) << "\","
        << "\"source_parameter\":\"" << json_escape(layer.source_parameter) << "\","
        << "\"mask_parameter\":\"" << json_escape(layer.mask_parameter) << "\","
        << "\"diffuse_source\":\"" << json_escape(layer.diffuse_source) << "\","
        << "\"diffuse_archive_path\":\"" << json_escape(layer.diffuse_archive_path) << "\","
        << "\"normal_source\":\"" << json_escape(layer.normal_source) << "\","
        << "\"normal_archive_path\":\"" << json_escape(layer.normal_archive_path) << "\","
        << "\"material_source\":\"" << json_escape(layer.material_source) << "\","
        << "\"material_archive_path\":\"" << json_escape(layer.material_archive_path) << "\","
        << "\"height_source\":\"" << json_escape(layer.height_source) << "\","
        << "\"height_archive_path\":\"" << json_escape(layer.height_archive_path) << "\","
        << "\"mask_source\":\"" << json_escape(layer.mask_source) << "\","
        << "\"mask_archive_path\":\"" << json_escape(layer.mask_archive_path) << "\","
        << "\"weight\":" << layer.weight << ","
        << "\"detail_scale\":" << layer.detail_scale << ","
        << "\"roughness_hint\":" << layer.roughness_hint << ","
        << "\"metalness_hint\":" << layer.metalness_hint << ","
        << "\"specular_hint\":" << layer.specular_hint << ","
        << "\"height_scale_hint\":" << layer.height_scale_hint << ","
        << "\"tint\":[" << layer.tint[0] << "," << layer.tint[1] << "," << layer.tint[2] << "," << layer.tint[3] << "]"
        << "}";
    return out.str();
}

static bool preview_color_is_tinted(const std::array<float, 3>& color) {
    const float max_component = std::max({color[0], color[1], color[2]});
    const float min_component = std::min({color[0], color[1], color[2]});
    return (max_component - min_component) > 0.055f;
}

static bool layer_tint_is_visible(const MaterialLayer& layer) {
    const float max_component = std::max({layer.tint[0], layer.tint[1], layer.tint[2]});
    const float min_component = std::min({layer.tint[0], layer.tint[1], layer.tint[2]});
    return (max_component - min_component) > 0.075f || layer.metalness_hint > 0.35f;
}

static bool tint_color_is_visible(const std::array<float, 4>& tint) {
    const float max_component = std::max({tint[0], tint[1], tint[2]});
    const float min_component = std::min({tint[0], tint[1], tint[2]});
    return (max_component - min_component) > 0.055f || std::abs(max_component - 1.0f) > 0.08f || std::abs(tint[3] - 1.0f) > 0.08f;
}

static bool tint_rgb_is_visible(const std::array<float, 4>& tint) {
    const float max_component = std::max({tint[0], tint[1], tint[2]});
    const float min_component = std::min({tint[0], tint[1], tint[2]});
    return (max_component - min_component) > 0.055f || std::abs(max_component - 1.0f) > 0.08f;
}

static bool binding_is_tintable_visible_layer_base(const TextureBinding* base) {
    if (base == nullptr) return false;
    const std::string descriptor = lower_copy(
        base->archive_path + " " + base->texture_name + " " + base->parameter_name + " " + base->layer_role + " " + base->visible_class
    );
    return descriptor.find("texturelayer") != std::string::npos
        || descriptor.find("grime") != std::string::npos
        || descriptor.find("detail") != std::string::npos
        || descriptor.find("dyeing") != std::string::npos
        || descriptor.find("layer_visible") != std::string::npos;
}

static bool reliable_visible_base_texture(const TextureBinding* base);

static bool weapon_metal_base_tint_should_stay_masked(const TextureBinding* base, const NativeSubmesh& mesh) {
    if (base == nullptr) return false;
    if (!mesh_has_crimson_weapon_surface(mesh) || mesh_local_surface_has_strong_nonmetal_token(mesh)) return false;
    if (!binding_is_tintable_visible_layer_base(base)) return false;
    const std::string channel = lower_copy(base->layer_channel);
    const std::string parameter = normalized_key(base->parameter_name);
    return channel == "g"
        || channel == "b"
        || channel == "a"
        || parameter.find("diffusetextureg") != std::string::npos
        || parameter.find("diffusetextureb") != std::string::npos
        || parameter.find("diffusetexturea") != std::string::npos
        || parameter.find("diffusemaskg") != std::string::npos
        || parameter.find("diffusemaskb") != std::string::npos
        || parameter.find("diffusemaska") != std::string::npos;
}

static bool mesh_prefers_sidecar_dye_tint(const NativeSubmesh& mesh) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return mesh_has_crimson_weapon_surface(mesh)
        || evidence.find("/9_upperbody/") != std::string::npos
        || evidence.find("/10_lowerbody/") != std::string::npos
        || evidence.find("_ub_") != std::string::npos
        || evidence.find("_lb_") != std::string::npos
        || evidence_contains_token(evidence, "upperbody")
        || evidence_contains_token(evidence, "lowerbody")
        || evidence_contains_token(evidence, "pants")
        || evidence_contains_token(evidence, "trouser")
        || evidence_contains_token(evidence, "skirt")
        || evidence_contains_token(evidence, "dress")
        || evidence_contains_token(evidence, "tunic")
        || evidence_contains_token(evidence, "sleeve")
        || evidence_contains_token(evidence, "flag")
        || evidence_contains_token(evidence, "banner")
        || evidence_contains_token(evidence, "ribbon")
        || evidence_contains_token(evidence, "sash")
        || evidence_contains_token(evidence, "tassel")
        || evidence_contains_token(evidence, "fringe")
        || evidence_contains_token(evidence, "flap");
}

static bool mesh_prefers_apparel_sidecar_tint(const NativeSubmesh& mesh) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return evidence.find("/9_upperbody/") != std::string::npos
        || evidence.find("/10_lowerbody/") != std::string::npos
        || evidence.find("_ub_") != std::string::npos
        || evidence.find("_lb_") != std::string::npos
        || evidence_contains_token(evidence, "upperbody")
        || evidence_contains_token(evidence, "lowerbody")
        || evidence_contains_token(evidence, "pants")
        || evidence_contains_token(evidence, "trouser")
        || evidence_contains_token(evidence, "skirt")
        || evidence_contains_token(evidence, "dress")
        || evidence_contains_token(evidence, "tunic")
        || evidence_contains_token(evidence, "sleeve");
}

static float preview_tint_score(const std::array<float, 4>& tint) {
    if (!tint_color_is_visible(tint)) return -1.0f;
    const float max_component = std::max({tint[0], tint[1], tint[2]});
    const float min_component = std::min({tint[0], tint[1], tint[2]});
    const float luma = tint[0] * 0.299f + tint[1] * 0.587f + tint[2] * 0.114f;
    const float alpha = std::clamp(tint[3], 0.0f, 1.0f);
    return (max_component - min_component) * 1.60f + luma * 0.25f + alpha * 0.35f;
}

static std::array<float, 3> preview_tint_rgb_for_color(const std::array<float, 4>& tint) {
    return {
        std::clamp(tint[0], 0.02f, 1.35f),
        std::clamp(tint[1], 0.02f, 1.35f),
        std::clamp(tint[2], 0.02f, 1.35f),
    };
}

static float preview_tint_chroma_distance(const std::array<float, 4>& left, const std::array<float, 4>& right) {
    const float left_luma = std::max(left[0] * 0.299f + left[1] * 0.587f + left[2] * 0.114f, 0.08f);
    const float right_luma = std::max(right[0] * 0.299f + right[1] * 0.587f + right[2] * 0.114f, 0.08f);
    return std::abs(left[0] / left_luma - right[0] / right_luma)
        + std::abs(left[1] / left_luma - right[1] / right_luma)
        + std::abs(left[2] / left_luma - right[2] / right_luma);
}

static void filter_material_layers_for_visible_tint(
    std::vector<MaterialLayer>& layers,
    const std::array<float, 4>& visible_tint,
    const NativeSubmesh& mesh
) {
    if (layers.size() <= 2 || !mesh_has_crimson_weapon_surface(mesh) || !tint_color_is_visible(visible_tint)) return;
    std::vector<MaterialLayer> kept;
    kept.reserve(layers.size());
    for (size_t index = 0; index < layers.size(); ++index) {
        const MaterialLayer& layer = layers[index];
        if (index == 0 || !tint_color_is_visible(layer.tint)) {
            kept.push_back(layer);
            continue;
        }
        const std::string role = lower_copy(layer.layer_role);
        const bool tint_layer = role.find("detail") != std::string::npos || role.find("grime") != std::string::npos || role.find("layer") != std::string::npos;
        if (!tint_layer || preview_tint_chroma_distance(visible_tint, layer.tint) <= 1.65f) {
            kept.push_back(layer);
        }
    }
    if (!kept.empty()) layers.swap(kept);
}

static std::array<float, 3> preview_tint_rgb_for_binding(const TextureBinding* base) {
    if (base == nullptr || !tint_color_is_visible(base->tint_color)) {
        return {1.0f, 1.0f, 1.0f};
    }
    return preview_tint_rgb_for_color(base->tint_color);
}

static bool nonmetal_equipment_texturelayer_base(
    const TextureBinding* base,
    const NativeSubmesh& mesh,
    const std::string& material_category
) {
    if (base == nullptr) return false;
    const std::string category = lower_copy(material_category);
    if (category != "cloth" && category != "leather" && category != "skin" && category != "hair") return false;
    const std::string base_text = lower_copy(base->archive_path + " " + base->texture_name + " " + base->parameter_name);
    if (base_text.find("texturelayer") == std::string::npos) return false;
    std::string evidence = lower_copy(mesh.source_model_path + " " + mesh.source_component_label + " " + mesh.material + " " + mesh.name);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return evidence.find("character/model/") != std::string::npos
        && (
            evidence.find("/armor/") != std::string::npos
            || evidence.find("/nude/") != std::string::npos
            || evidence.find("/hair/") != std::string::npos
            || evidence.find("/2_mon/") != std::string::npos
        );
}

static bool nonmetal_equipment_texturelayer_without_tint(
    const TextureBinding* base,
    const NativeSubmesh& mesh,
    const std::string& material_category,
    bool visible_layer_tint_applied
) {
    return !visible_layer_tint_applied && !tint_rgb_is_visible(base == nullptr ? std::array<float, 4>{1.0f, 1.0f, 1.0f, 1.0f} : base->tint_color)
        && nonmetal_equipment_texturelayer_base(base, mesh, material_category);
}

static bool nonmetal_surface_category(const std::string& material_category) {
    const std::string category = lower_copy(material_category);
    return category == "cloth" || category == "leather" || category == "skin" || category == "hair";
}

static bool emissive_binding_is_safe_for_preview(
    const TextureBinding* emissive,
    const NativeSubmesh& mesh,
    const std::string& material_category
) {
    if (emissive == nullptr) return false;
    if (emissive->emissive_intensity_hint <= 0.001f) return false;
    const std::string evidence = lower_copy(
        emissive->archive_path + " " + emissive->texture_name + " " + emissive->material_name + " " +
        mesh.material + " " + mesh.name + " " + mesh.source_model_path
    );
    const bool direct_texture_evidence = direct_emissive_texture_or_shader_evidence(emissive->archive_path, emissive->texture_name, "");
    if (evidence.find("effect/texture/") != std::string::npos && evidence.find("character/model/") != std::string::npos && !direct_texture_evidence) {
        return false;
    }
    if (nonmetal_surface_category(material_category)) {
        return direct_texture_evidence;
    }
    if (direct_emissive_texture_or_shader_evidence(emissive->archive_path, emissive->texture_name, emissive->shader_family)) {
        return true;
    }
    return true;
}

static std::array<float, 3> fallback_nonmetal_equipment_layer_color(
    const std::string& material_category,
    const NativeSubmesh& mesh,
    const TextureBinding* base
) {
    const std::string category = lower_copy(material_category);
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    if (base != nullptr) {
        evidence += " " + lower_copy(base->archive_path + " " + base->texture_name + " " + base->parameter_name);
    }
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    if (category == "cloth" && (evidence_contains_token(evidence, "uw") || evidence_contains_token(evidence, "underwear"))) {
        return {0.88f, 0.82f, 0.72f};
    }
    if (category == "skin") return {0.72f, 0.54f, 0.44f};
    if (category == "hair") return {0.30f, 0.27f, 0.24f};
    if (category == "leather") return {0.36f, 0.29f, 0.22f};
    return {0.46f, 0.42f, 0.35f};
}

static bool preview_sidecar_tint_for_surface(
    const TextureBinding* base,
    const NativeSubmesh& mesh,
    const std::vector<MaterialLayer>& material_layers,
    std::array<float, 4>* tint_out
) {
    if (base == nullptr || tint_out == nullptr) return false;
    if (weapon_metal_base_tint_should_stay_masked(base, mesh)) {
        return false;
    }
    const bool tintable_layer_base = binding_is_tintable_visible_layer_base(base);
    const bool wrong_family_nonmetal_layer_base =
        base_binding_is_wrong_family_layer_or_environment(*base, mesh)
        && mesh_local_surface_has_strong_nonmetal_token(mesh);
    const bool masked_tint_layer = std::any_of(
        material_layers.begin(),
        material_layers.end(),
        [](const MaterialLayer& layer) {
            return layer.layer_role != "base"
                && !layer.mask_source.empty()
                && tint_color_is_visible(layer.tint);
        });
    if (reliable_visible_base_texture(base) && masked_tint_layer) {
        // A selector/detail tint owns only the texels named by its mask.  The
        // layer compiler already applies it there; promoting the same colour to
        // a global base tint recoloured neutral chain mail and cloth outside the
        // mask, which is why a silver hood appeared gold in the preview.
        return false;
    }
    if (tintable_layer_base && tint_rgb_is_visible(base->tint_color) && !wrong_family_nonmetal_layer_base) {
        *tint_out = base->tint_color;
        return true;
    }
    if (!mesh_prefers_sidecar_dye_tint(mesh) && !wrong_family_nonmetal_layer_base) return false;
    if (mesh_prefers_apparel_sidecar_tint(mesh) && tint_rgb_is_visible(base->tint_color)) {
        *tint_out = base->tint_color;
        return true;
    }
    std::array<float, 4> best_tint = base->tint_color;
    float best_score = tint_rgb_is_visible(best_tint) ? preview_tint_score(best_tint) : -1.0f;
    for (const MaterialLayer& layer : material_layers) {
        if (layer.layer_role == "base") continue;
        float score = preview_tint_score(layer.tint);
        if (layer.layer_role == "detail") score += 0.18f;
        if (layer.layer_role == "grime") score += 0.06f;
        if (wrong_family_nonmetal_layer_base && tint_color_is_visible(layer.tint)) score += 0.26f;
        score += std::clamp(layer.weight, 0.0f, 1.0f) * 0.10f;
        if (score > best_score) {
            best_score = score;
            best_tint = layer.tint;
        }
    }
    if (best_score <= 0.0f) return false;
    *tint_out = best_tint;
    return true;
}

static float visible_layer_albedo_tint_strength(const TextureBinding* base, bool visible_layer_tint_applied) {
    if (!visible_layer_tint_applied || !binding_is_tintable_visible_layer_base(base) || !tint_color_is_visible(base->tint_color)) {
        return 0.0f;
    }
    const float chroma = std::max({base->tint_color[0], base->tint_color[1], base->tint_color[2]})
        - std::min({base->tint_color[0], base->tint_color[1], base->tint_color[2]});
    const float alpha = std::clamp(base->tint_color[3], 0.0f, 1.0f);
    return std::clamp(0.52f + chroma * 0.26f + alpha * 0.10f, 0.45f, 0.82f);
}

static bool reliable_visible_base_texture(const TextureBinding* base) {
    if (base == nullptr || base->source_path.empty()) return false;
    if (base->visible_class == "technical") return false;
    if (base->material_output_quality != "exact") return false;
    return base->source_authority == "exact_sidecar" || base->source_authority == "embedded_mesh";
}

static float native_preview_base_tint_strength(
    const TextureBinding* base,
    const std::array<float, 3>& color,
    const std::vector<MaterialLayer>& material_layers,
    bool visible_layer_tint_applied = false,
    bool force_nonmetal_equipment_layer_tint = false
) {
    if (force_nonmetal_equipment_layer_tint) return preview_color_is_tinted(color) ? 0.30f : 0.0f;
    const float visible_layer_strength = visible_layer_albedo_tint_strength(base, visible_layer_tint_applied);
    if (visible_layer_strength > 0.0f) return visible_layer_strength;
    if (visible_layer_tint_applied && preview_color_is_tinted(color)) {
        if (base != nullptr && reliable_visible_base_texture(base) && base->visible_class == "primary_visible") {
            const float max_component = std::max({color[0], color[1], color[2]});
            const float min_component = std::min({color[0], color[1], color[2]});
            return std::clamp(0.24f + (max_component - min_component) * 0.28f, 0.22f, 0.42f);
        }
        const float max_component = std::max({color[0], color[1], color[2]});
        const float min_component = std::min({color[0], color[1], color[2]});
        const float chroma = max_component - min_component;
        return std::clamp(0.58f + chroma * 0.22f + max_component * 0.12f, 0.58f, 0.88f);
    }
    if (base == nullptr || !preview_color_is_tinted(color)) return 0.0f;
    if (reliable_visible_base_texture(base)) return 0.0f;
    float strength = lower_copy(base->archive_path).find("texturelayer") != std::string::npos ? 0.48f : 0.30f;
    for (const MaterialLayer& layer : material_layers) {
        if (layer.layer_role == "base") continue;
        if (layer_tint_is_visible(layer)) {
            strength = std::max(strength, layer.layer_role == "detail" ? 0.42f : 0.36f);
        }
    }
    return std::clamp(strength, 0.0f, 0.58f);
}

static bool job_allows_texture_role(const EntryJob& job, const std::string& role) {
    if (!job.use_textures) return false;
    if (role == "base") return true;
    if (job.disable_all_support_maps) return false;
    if (role == "normal") return !job.disable_normal_map;
    if (role == "height") return !job.disable_height_map;
    if (
        role == "material"
        || role == "occlusion"
        || role == "roughness"
        || role == "metalness"
        || role == "specular"
        || role == "detail"
    ) {
        return !job.disable_material_map;
    }
    return true;
}
