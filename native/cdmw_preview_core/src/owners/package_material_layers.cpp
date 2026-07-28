
static std::string material_category_reason_for_bindings(
    const std::string& category,
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* base,
    const std::vector<MaterialLayer>& layers,
    const TextureBinding* surface
) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    if (base != nullptr) {
        evidence += " " + lower_copy(base->archive_path + " " + base->texture_name + " " + base->parameter_name + " " + base->shader_rule + " " + base->shader_family);
    }
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        evidence += " " + lower_copy(binding->archive_path + " " + binding->texture_name + " " + binding->parameter_name + " " + binding->shader_rule + " " + binding->shader_family);
    }
    for (const MaterialLayer& layer : layers) {
        evidence += " " + lower_copy(layer.diffuse_archive_path + " " + layer.source_parameter + " " + layer.layer_role);
    }
    const DecodedSurfaceEvidence decoded = decoded_surface_evidence(bindings, surface);
    if (decoded.decoded) {
        // Report the measurement rather than the rule it replaced, so a reader can
        // tell a decoded verdict from a slot-position guess.
        if (category == "metal" && decoded.metal_coverage >= kDecodedMetalDominantCoverage) {
            return "metal:decoded_metal_channel:"
                + std::to_string(static_cast<int>(decoded.metal_coverage * 100.0f + 0.5f)) + "pct";
        }
        if (category != "metal" && decoded.metal_coverage < kDecodedMetalDominantCoverage) {
            return decoded.metal_coverage < kDecodedMetalAbsentCoverage
                ? "nonmetal:decoded_metal_channel_absent"
                : "nonmetal:decoded_metal_channel_minority:"
                    + std::to_string(static_cast<int>(decoded.metal_coverage * 100.0f + 0.5f)) + "pct";
        }
    }
    if (category == "metal") {
        if (mesh_has_crimson_armor_equipment_surface(mesh) && has_authoritative_equipment_material_response(bindings, mesh)) {
            return "metal:armor_family_material_response";
        }
        if (mesh_has_crimson_weapon_surface(mesh) && has_authoritative_model_family_material_response(bindings, mesh)) {
            return "metal:weapon_family_material_response";
        }
        for (const char* token : {"gold", "silver", "copper", "bronze", "brass", "chrome"}) {
            if (evidence_contains_token(evidence, token)) return std::string("metal:color_token:") + token;
        }
        if (std::any_of(bindings.begin(), bindings.end(), [](const TextureBinding* binding) {
            return binding_has_explicit_metalness_slot(binding);
        })) {
            return "metal:material_channel";
        }
        for (const char* token : {"metal", "steel", "iron", "blade", "plate", "guard", "hilt", "chain", "helmet", "helm", "armor", "armour"}) {
            if (evidence_contains_token(evidence, token)) return std::string("metal:material_or_part_token:") + token;
        }
        return "metal:material_or_part_token";
    }
    if (category == "cloth") {
        if (
            evidence.find("/9_upperbody/") != std::string::npos
            || evidence.find("/10_lowerbody/") != std::string::npos
            || evidence.find("_ub_") != std::string::npos
            || evidence.find("_lb_") != std::string::npos
            || evidence_contains_token(evidence, "upperbody")
            || evidence_contains_token(evidence, "lowerbody")
        ) {
            return "nonmetal:apparel_slot_token";
        }
        return "nonmetal:cloth_token";
    }
    if (category == "leather") return "nonmetal:leather_or_handle_token";
    if (category == "wood") return "nonmetal:wood_token";
    if (category == "glass") return "glossy_nonmetal:glass_token";
    if (category == "gem") return "glossy_nonmetal:gem_token";
    if (category == "stone") return "nonmetal:stone_token";
    if (category == "eye") return "glossy_nonmetal:eye_surface_token";
    if (category == "tooth") return "nonmetal:tooth_token";
    if (category == "skin") return "nonmetal:skin_token";
    if (category == "hair") return "nonmetal:hair_token";
    return "generic:no_strong_material_token";
}

static float material_category_confidence(const std::string& category, const std::vector<const TextureBinding*>& bindings, const TextureBinding* base) {
    float confidence = category == "generic" ? 0.35f : 0.66f;
    if (base != nullptr && base->source_authority == "exact_sidecar") confidence += 0.10f;
    if (base_binding_is_low_authority_overlay(base)) confidence -= 0.12f;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        if (binding->material_output_quality == "exact") confidence += 0.02f;
        if (binding->material_wrapper_order_authoritative) confidence += 0.02f;
    }
    return std::clamp(confidence, 0.20f, 0.95f);
}

static bool promoted_global_material_response(const TextureBinding* material) {
    if (material == nullptr) return false;
    const std::string packed = lower_copy(material->packed_channels);
    const std::string parameter_key = normalized_key(material->parameter_name);
    const std::string path = lower_copy(material->archive_path + " " + material->texture_name);
    if (packed.find("r=occlusion") != std::string::npos && packed.find("g=roughness") != std::string::npos && packed.find("b=metalness") != std::string::npos) {
        return true;
    }
    return parameter_key == "colorblendingmasktexture" && path.find("_ma") != std::string::npos;
}

static std::string material_response_disposition(const TextureBinding* material, const TextureBinding* specular, const std::string& category) {
    if (material == nullptr && specular == nullptr) return "none";
    if (promoted_global_material_response(material)) {
        return category == "metal" ? "promoted_metallic_roughness" : "promoted_ao_roughness_nonmetal_capped";
    }
    if (specular != nullptr) {
        return category == "metal" ? "specular_gloss_metal_response" : "specular_gloss_nonmetal_capped";
    }
    const std::string packed = lower_copy(material == nullptr ? "" : material->packed_channels);
    if (packed.find("layer:") != std::string::npos) return "layer_only";
    return "diagnostic_only";
}

static bool layer_channel_matches(const TextureBinding& binding, const std::string& channel) {
    return binding.layer_channel.empty() || channel.empty() || binding.layer_channel == channel;
}

static const TextureBinding* find_layer_aux_binding(
    const std::vector<const TextureBinding*>& bindings,
    const std::string& desired_role,
    const std::string& layer_role,
    const std::string& channel
) {
    const TextureBinding* best = nullptr;
    int best_score = -1000;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr || binding->source_path.empty()) continue;
        int score = -1000;
        const std::string parameter = normalized_key(binding->parameter_name);
        const std::string binding_layer = lower_copy(binding->layer_role);
        if (desired_role == "mask") {
            if (layer_role == "detail" && (parameter.find("detailmask") != std::string::npos || binding->role == "detail")) score = 120;
            else if ((layer_role == "grime" || layer_role == "layer") && (parameter.find("colorblendingmask") != std::string::npos || parameter.find("blendingmask") != std::string::npos)) score = 118;
            else if (layer_role == "damage" && parameter.find("mask") != std::string::npos) score = 104;
            else if (binding->role == "detail") score = 42;
        } else if (desired_role == "normal") {
            if (binding->role == "normal") score = 72;
            if (parameter.find(layer_role + "normal") != std::string::npos) score += 60;
            if (parameter.find("detailnormal") != std::string::npos && layer_role == "detail") score += 60;
            if (parameter.find("grimenormal") != std::string::npos && layer_role == "grime") score += 60;
        } else if (desired_role == "material") {
            if (binding->role == "material" || binding->role == "specular") score = 62;
            if (parameter.find(layer_role + "material") != std::string::npos) score += 64;
            if (parameter.find("detailmaterial") != std::string::npos && layer_role == "detail") score += 64;
            if (parameter.find("grimematerial") != std::string::npos && layer_role == "grime") score += 64;
        } else if (desired_role == "height") {
            if (binding->role == "height") score = 52;
            if (parameter.find(layer_role + "height") != std::string::npos) score += 66;
            if (parameter.find("detailheight") != std::string::npos && layer_role == "detail") score += 66;
        }
        if (score <= -1000) continue;
        if (binding_layer == layer_role) score += 18;
        if (layer_channel_matches(*binding, channel)) score += 24;
        else score -= 18;
        if (score > best_score) {
            best_score = score;
            best = binding;
        }
    }
    return best_score >= 40 ? best : nullptr;
}

static MaterialLayer make_base_material_layer(
    const TextureBinding* base,
    const TextureBinding* normal,
    const TextureBinding* material,
    const TextureBinding* height,
    const TextureBinding* specular,
    const NativeMaterialHints& hints
) {
    MaterialLayer layer;
    layer.layer_role = "base";
    layer.layer_channel = base != nullptr && !base->layer_channel.empty() ? base->layer_channel : "r";
    layer.shader_family = base != nullptr ? base->shader_family : "";
    layer.shader_rule = base != nullptr ? base->shader_rule : "";
    layer.evidence_grade = base != nullptr ? base->evidence_grade : "approximate";
    layer.weight = 1.0f;
    layer.roughness_hint = hints.roughness;
    layer.metalness_hint = hints.metalness;
    layer.specular_hint = hints.specular;
    layer.height_scale_hint = hints.height_scale;
    if (base != nullptr) {
        layer.diffuse_source = base->source_path;
        layer.diffuse_archive_path = base->archive_path;
        layer.source_parameter = base->parameter_name;
        layer.tint = base->tint_color;
    }
    if (normal != nullptr) {
        layer.normal_source = normal->source_path;
        layer.normal_archive_path = normal->archive_path;
    }
    const TextureBinding* material_response = material != nullptr ? material : specular;
    if (material_response != nullptr) {
        layer.material_source = material_response->source_path;
        layer.material_archive_path = material_response->archive_path;
    }
    if (height != nullptr) {
        layer.height_source = height->source_path;
        layer.height_archive_path = height->archive_path;
    }
    return layer;
}

static bool tint_color_is_visible(const std::array<float, 4>& tint);

// How much of the surface a layer is allowed to claim. A weapon's layer stack is
// its whole finish rather than an accent, so those layers carry far more weight
// than the general case, and a tinted detail layer on a weapon sits between the
// two. An unauthored weight (<= 0.001) falls back to the band's default.
static void apply_layer_weight_and_tint_policy(
    MaterialLayer& layer,
    bool weapon_layer_stack,
    bool weapon_tinted_detail_layer,
    bool selected_base_layer
) {
    if (weapon_layer_stack) {
        const bool detail_layer = lower_copy(layer.layer_role).find("detail") != std::string::npos;
        const float fallback_weight = selected_base_layer ? 0.48f : (detail_layer ? 0.44f : 0.36f);
        const float minimum_weight = selected_base_layer ? 0.42f : (detail_layer ? 0.34f : 0.28f);
        layer.weight = std::clamp(layer.weight <= 0.001f ? fallback_weight : layer.weight, 0.0f, 0.78f);
        layer.weight = std::max(layer.weight, minimum_weight);
        if (layer.tint[3] < 0.55f) {
            layer.tint[3] = detail_layer ? 0.68f : 0.55f;
        }
        return;
    }
    if (weapon_tinted_detail_layer) {
        layer.weight = std::clamp(layer.weight <= 0.001f ? 0.58f : layer.weight, 0.0f, 0.72f);
        layer.weight = std::max(layer.weight, 0.44f);
        if (layer.tint[3] < 0.68f) {
            layer.tint[3] = 0.68f;
        }
        return;
    }
    layer.weight = std::clamp(layer.weight <= 0.001f ? 0.14f : layer.weight, 0.0f, 0.22f);
}

static std::vector<MaterialLayer> compile_material_layers(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* base,
    const TextureBinding* normal,
    const TextureBinding* material,
    const TextureBinding* height,
    const TextureBinding* specular,
    const NativeMaterialHints& hints,
    const std::string& visible_texture_mode
) {
    std::vector<MaterialLayer> layers;
    layers.push_back(make_base_material_layer(base, normal, material, height, specular, hints));
    const std::string mode = normalize_visible_texture_mode(visible_texture_mode);
    if (shader_rule_holds_layer_albedo(bindings)) {
        return layers;
    }
    if (mode == "mesh_base_first" && !shader_rule_supports_conservative_layer_stack(bindings)) {
        return layers;
    }
    const bool weapon_layer_stack =
        mesh_has_crimson_weapon_surface(mesh)
        && !mesh_local_surface_has_strong_nonmetal_token(mesh)
        && (
            hints.metalness > 0.08f
            || has_authoritative_model_family_material_response(bindings, mesh)
        );
    std::set<std::string> seen_layer_keys;
    for (const TextureBinding* binding : bindings) {
        const bool selected_base_layer = binding == base;
        if (binding == nullptr || !binding_is_layer_diffuse(*binding, base, weapon_layer_stack && selected_base_layer)) continue;
        const std::string binding_shader_rule = lower_copy(binding->shader_rule);
        const std::string binding_shader_family = lower_copy(binding->shader_family);
        const bool held_shader =
            binding_shader_rule == "hair"
            || binding_shader_rule == "skin"
            || binding_shader_family.find("skinnedmeshhair") != std::string::npos
            || binding_shader_family.find("skinnedmeshskin") != std::string::npos
            || binding_shader_family.find("wrinkle") != std::string::npos;
        if ((binding_shader_rule.find("generic") != std::string::npos && binding->pbd_simulation_material_name.empty()) || held_shader) {
            continue;
        }
        const std::string layer_key =
            lower_copy(binding->archive_path)
            + "|" + lower_copy(binding->layer_role)
            + "|" + lower_copy(binding->layer_channel);
        if (!seen_layer_keys.insert(layer_key).second) {
            continue;
        }
        MaterialLayer layer;
        layer.layer_role = binding->layer_role.empty() || binding->layer_role == "base" ? "layer" : binding->layer_role;
        layer.layer_channel = binding->layer_channel.empty() ? "r" : binding->layer_channel;
        layer.shader_family = binding->shader_family;
        layer.shader_rule = binding->shader_rule;
        layer.evidence_grade = binding->evidence_grade;
        layer.weight = std::clamp(binding->layer_weight, 0.0f, 1.0f);
        layer.tint = binding->tint_color;
        layer.diffuse_source = binding->source_path;
        layer.diffuse_archive_path = binding->archive_path;
        layer.source_parameter = binding->parameter_name;
        layer.blend_order = "base_then_" + layer.layer_role;
        const TextureBinding* mask = find_layer_aux_binding(bindings, "mask", layer.layer_role, layer.layer_channel);
        const TextureBinding* layer_normal = find_layer_aux_binding(bindings, "normal", layer.layer_role, layer.layer_channel);
        const TextureBinding* layer_material = find_layer_aux_binding(bindings, "material", layer.layer_role, layer.layer_channel);
        const TextureBinding* layer_height = find_layer_aux_binding(bindings, "height", layer.layer_role, layer.layer_channel);
        if (mask == nullptr) {
            continue;
        }
        if (placeholder_layer_mask_path(mask->archive_path) || placeholder_layer_mask_path(mask->texture_name)) {
            continue;
        }
        // The layer parameter says which channel of the mask selects it, so it
        // outranks anything read off the mask binding. `_detailMaskTexture`
        // resolves to a fixed "b", and letting that overwrite the layer put
        // `_detailDiffuseMaskR`, `G` and `B` all on the blue channel: two of the
        // three layers painted in the wrong regions and the areas the red and
        // green channels mark got nothing, which is why a fully layered helmet
        // like cd_phm_00_hel_00_0354 collapsed to one flat tone. The mask's own
        // channel is still the fallback for layers that name none.
        if (!mask->layer_channel.empty()
            && !layer_parameter_names_channel(binding->parameter_name)) {
            layer.layer_channel = mask->layer_channel;
        }
        layer.mask_source = mask->source_path;
        layer.mask_archive_path = mask->archive_path;
        layer.mask_parameter = mask->parameter_name;
        const bool weapon_tinted_detail_layer =
            mesh_has_crimson_weapon_surface(mesh)
            && lower_copy(layer.layer_role).find("detail") != std::string::npos
            && tint_color_is_visible(layer.tint);
        apply_layer_weight_and_tint_policy(
            layer, weapon_layer_stack, weapon_tinted_detail_layer, selected_base_layer);
        if (base != nullptr && base->dds_width > 0 && base->dds_height > 0 && binding->dds_width > 0 && binding->dds_height > 0) {
            const int base_largest_dimension = std::max(base->dds_width, base->dds_height);
            const int layer_largest_dimension = std::max(binding->dds_width, binding->dds_height);
            if (weapon_layer_stack || weapon_tinted_detail_layer) {
                if (layer_largest_dimension * 2 < base_largest_dimension) {
                    layer.weight *= weapon_layer_stack ? 0.72f : 0.86f;
                } else if (layer_largest_dimension < base_largest_dimension) {
                    layer.weight *= weapon_layer_stack ? 0.86f : 0.94f;
                }
            } else {
                if (layer_largest_dimension * 2 < base_largest_dimension) {
                    layer.weight *= 0.45f;
                } else if (layer_largest_dimension < base_largest_dimension) {
                    layer.weight *= 0.72f;
                }
            }
        }
        if (layer_normal != nullptr) {
            layer.normal_source = layer_normal->source_path;
            layer.normal_archive_path = layer_normal->archive_path;
        }
        if (layer_material != nullptr) {
            layer.material_source = layer_material->source_path;
            layer.material_archive_path = layer_material->archive_path;
            layer.roughness_hint = std::max(layer.roughness_hint, layer_material->roughness_hint);
            layer.metalness_hint = std::max(layer.metalness_hint, layer_material->metalness_hint);
            layer.specular_hint = std::max(layer.specular_hint, layer_material->specular_hint);
        }
        if (layer_height != nullptr) {
            layer.height_source = layer_height->source_path;
            layer.height_archive_path = layer_height->archive_path;
            layer.height_scale_hint = std::max(layer.height_scale_hint, layer_height->height_scale_hint);
        }
        layers.push_back(layer);
        if ((!weapon_layer_stack && layers.size() >= 5) || (weapon_layer_stack && layers.size() >= 9)) break;
    }
    if (weapon_layer_stack && layers.size() > 5) {
        std::vector<MaterialLayer> overlays(layers.begin() + 1, layers.end());
        std::stable_sort(overlays.begin(), overlays.end(), [base](const MaterialLayer& left, const MaterialLayer& right) {
            auto priority = [base](const MaterialLayer& layer) -> int {
                const bool selected_base_layer =
                    base != nullptr
                    && lower_copy(layer.diffuse_archive_path) == lower_copy(base->archive_path)
                    && lower_copy(layer.source_parameter) == lower_copy(base->parameter_name);
                if (selected_base_layer) return 0;
                const std::string role = lower_copy(layer.layer_role);
                if (role.find("detail") != std::string::npos) return 1;
                const float max_component = std::max({layer.tint[0], layer.tint[1], layer.tint[2]});
                const float min_component = std::min({layer.tint[0], layer.tint[1], layer.tint[2]});
                if ((max_component - min_component) > 0.075f || layer.metalness_hint > 0.35f) return 2;
                return 3;
            };
            return priority(left) < priority(right);
        });
        layers.erase(layers.begin() + 1, layers.end());
        layers.insert(layers.end(), overlays.begin(), overlays.begin() + std::min<size_t>(4, overlays.size()));
    }
    return layers;
}

static std::string material_layer_json(const MaterialLayer& layer) {
    std::ostringstream out;
    out << "{"
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
