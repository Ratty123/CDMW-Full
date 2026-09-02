
struct NativeMaterialHints {
    float roughness = 0.45f;
    float metalness = 0.0f;
    float specular = 0.45f;
    float height_scale = 0.35f;
    bool roughness_authored = false;
    bool metalness_authored = false;
    bool specular_authored = false;
    bool height_scale_authored = false;
};

struct SurfaceProfile {
    std::string family = "generic";
    int family_code = 0;
    std::string finish = "unspecified";
    std::string structure = "unspecified";
    std::string coating = "none";
    float confidence = 0.35f;
    std::string evidence;
    float fallback_roughness = 0.45f;
    float fallback_metalness = 0.0f;
    float fallback_specular = 0.20f;
    float fallback_height_scale = 0.0f;
    float fallback_anisotropy = 0.0f;
    bool roughness_authored = false;
    bool metalness_authored = false;
    bool specular_authored = false;
    bool height_scale_authored = false;
    bool roughness_fallback_applied = false;
    bool metalness_fallback_applied = false;
    bool specular_fallback_applied = false;
    bool height_scale_fallback_applied = false;
    bool anisotropy_fallback_applied = false;
};

static NativeMaterialHints clamp_material_hints_for_category(NativeMaterialHints hints, const std::string& category) {
    const std::string normalized = lower_copy(category);
    if (normalized == "cloth") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.28f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.48f);
    } else if (normalized == "leather") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.36f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.38f);
    } else if (normalized == "wood") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.30f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.44f);
    } else if (normalized == "skin") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.34f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.30f);
    } else if (normalized == "hair") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.46f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.36f);
    } else if (normalized == "stone" || normalized == "bone"
        || normalized == "organic" || normalized == "foliage") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.26f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.42f);
    } else if (normalized == "tooth") {
        if (!hints.metalness_authored) hints.metalness = 0.0f;
        if (!hints.specular_authored) hints.specular = std::min(hints.specular, 0.26f);
        if (!hints.roughness_authored) hints.roughness = std::max(hints.roughness, 0.42f);
    }
    return hints;
}

static NativeMaterialHints material_hints_for_bindings(const std::vector<const TextureBinding*>& bindings) {
    NativeMaterialHints hints;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string packed = lower_copy(binding->packed_channels + " " + binding->parameter_name);
        const bool response_map = !binding_is_layer_selector_mask(*binding)
            && (binding->role == "material" || binding->role == "specular");
        hints.roughness_authored = hints.roughness_authored
            || binding->roughness_hint_present
            || (response_map && (binding->role == "specular" || packed.find("rough") != std::string::npos));
        hints.metalness_authored = hints.metalness_authored
            || binding->metalness_hint_present
            || (response_map && packed.find("metal") != std::string::npos);
        hints.specular_authored = hints.specular_authored
            || binding->specular_hint_present || binding->role == "specular";
        hints.height_scale_authored = hints.height_scale_authored
            || binding->height_scale_hint_present;
        roughness_hint = std::max(roughness_hint, binding->roughness_hint);
        metalness_hint = std::max(metalness_hint, binding->metalness_hint);
        specular_hint = std::max(specular_hint, binding->specular_hint);
        height_scale_hint = std::max(height_scale_hint, binding->height_scale_hint);
    }
    if (hints.roughness_authored) hints.roughness = std::clamp(roughness_hint, 0.0f, 1.0f);
    if (hints.metalness_authored) hints.metalness = std::clamp(metalness_hint, 0.0f, 1.0f);
    if (hints.specular_authored) hints.specular = std::clamp(specular_hint, 0.0f, 1.0f);
    if (hints.height_scale_authored) hints.height_scale = std::clamp(height_scale_hint, 0.0f, 1.0f);
    return hints;
}

static bool binding_is_layer_diffuse(
    const TextureBinding& binding,
    const TextureBinding* selected_base,
    bool allow_selected_base_as_layer = false
) {
    if (binding.role != "base") return false;
    if (&binding == selected_base && !allow_selected_base_as_layer) return false;
    if (placeholder_visible_base_path(binding.archive_path) || placeholder_visible_base_path(binding.texture_name)) return false;
    if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)) return false;
    const std::string role = lower_copy(binding.layer_role);
    if (role == "overlay") return false;
    if (role == "detail" || role == "grime" || role == "damage" || role == "layer") return true;
    if (binding.visible_class == "layer_visible") return true;
    const std::string parameter = normalized_key(binding.parameter_name);
    return parameter.find("detaildiffuse") != std::string::npos
        || parameter.find("grimediffuse") != std::string::npos
        || (
            parameter.find("colortexture") != std::string::npos
            && parameter.find("overlaycolor") == std::string::npos
        );
}

static bool shader_rule_holds_layer_albedo(const std::vector<const TextureBinding*>& bindings) {
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string shader_rule = lower_copy(binding->shader_rule);
        const std::string shader_family = lower_copy(binding->shader_family);
        const std::string rule = shader_rule + " " + shader_family;
        if (
            shader_rule == "skin"
            || shader_family.find("skinnedmeshskin") != std::string::npos
            || rule.find("wrinkle") != std::string::npos
            || shader_rule == "hair"
            || shader_family.find("skinnedmeshhair") != std::string::npos
        ) {
            return true;
        }
    }
    return false;
}

static bool exact_authored_layer_binding_matches_mesh(
    const TextureBinding& binding,
    const NativeSubmesh& mesh
) {
    if (binding.source_authority != "exact_sidecar"
        || binding.material_output_quality != "exact"
        || !binding.material_wrapper_order_authoritative
        || binding.material_wrapper_index < 0
        || binding.sidecar_path.empty()
        || !material_binding_matches_mesh_source(binding, mesh)) {
        return false;
    }
    return mesh.source_local_submesh_index < 0
        || binding.material_wrapper_index == mesh.source_local_submesh_index;
}

static bool shader_rule_supports_conservative_layer_stack(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh
) {
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string rule = lower_copy(binding->shader_rule + " " + binding->shader_family);
        if (
            rule.find("standard") != std::string::npos
            || rule.find("cloth") != std::string::npos
            || rule.find("multitextured") != std::string::npos
        ) {
            return true;
        }
        if (
            rule.find("generic") != std::string::npos
            && !binding->pbd_simulation_material_name.empty()
            && (
                binding->layer_role == "detail"
                || binding->layer_role == "grime"
                || binding->layer_role == "damage"
                || binding->layer_role == "layer"
                || binding->role == "detail"
            )
        ) {
            return true;
        }
        const std::string parameter = normalized_key(binding->parameter_name);
        const std::string layer_role = lower_copy(binding->layer_role);
        if (
            rule.find("emissive") != std::string::npos
            && exact_authored_layer_binding_matches_mesh(*binding, mesh)
            && binding->role == "base"
            && (layer_role == "detail" || layer_role == "grime"
                || layer_role == "damage" || layer_role == "layer")
            && (parameter.find("detaildiffuse") != std::string::npos
                || parameter.find("grimediffuse") != std::string::npos
                || parameter.find("dyediffuse") != std::string::npos)
        ) {
            return true;
        }
    }
    return false;
}

static const TextureBinding* best_visible_layer_base_fallback(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* selected_base,
    int* selected_score = nullptr,
    std::vector<std::string>* rejected_examples = nullptr
) {
    bool has_mesh_family_layer_base = false;
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        if (!binding_is_layer_diffuse(binding, selected_base)) continue;
        if (base_binding_is_low_authority_overlay(&binding)) continue;
        if (!material_binding_matches_mesh_source(binding, mesh)) continue;
        if (base_binding_texture_family_matches_mesh(binding, mesh)) {
            has_mesh_family_layer_base = true;
            break;
        }
    }
    const TextureBinding* best = nullptr;
    int best_score = 86;
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        if (!binding_is_layer_diffuse(binding, selected_base)) continue;
        if (base_binding_is_low_authority_overlay(&binding)) continue;
        if (!material_binding_matches_mesh_source(binding, mesh)) continue;
        if (
            binding.material_wrapper_order_authoritative
            && binding.material_wrapper_index >= 0
            && mesh.source_local_submesh_index >= 0
            && binding.material_wrapper_index != mesh.source_local_submesh_index
        ) {
            continue;
        }
        const int identity_score = material_identity_match_score(binding, mesh);
        if (binding.material_wrapper_order_authoritative && identity_score < 120) continue;
        if (base_binding_has_unsafe_cross_part_texture_family(binding, mesh)) {
            append_rejected_binding_example(rejected_examples, "base", "cross-part", binding, mesh, identity_score);
            continue;
        }
        const bool mesh_family_layer_base = base_binding_texture_family_matches_mesh(binding, mesh);
        const bool wrong_family_layer_base = base_binding_is_wrong_family_layer_or_environment(binding, mesh);
        if (wrong_family_layer_base && has_mesh_family_layer_base) {
            append_rejected_binding_example(rejected_examples, "base", "wrong-family-layer", binding, mesh, identity_score);
            continue;
        }
        int score = material_match_score(binding, mesh, "base") + visible_class_priority(binding.visible_class) * 22;
        const std::string parameter_key = normalized_key(binding.parameter_name);
        if (mesh_family_layer_base) score += 190;
        if (wrong_family_layer_base) score -= 260;
        if (binding.visible_class == "layer_visible") score += 72;
        // _grimeDiffuseTexture{R,G,B} are the three colour layers that
        // _colorBlendingMaskTexture selects -- they are the surface colour.
        // _detailDiffuseMask* are overlays selected by _detailMaskTexture.
        // Ranking detail above grime handed the base slot to an overlay: on
        // cd_phm_02_sword_0014 the blade's own wrapper offered
        // _detailDiffuseMaskR (score 184) and _grimeDiffuseTexture{R,G,B}
        // (168) at equal identity, so a detail layer became the albedo and the
        // authored colour layers were never used.
        if (parameter_key.find("grimediffuse") != std::string::npos) score += 50;
        if (parameter_key.find("detaildiffuse") != std::string::npos || parameter_key.find("detailcol") != std::string::npos) score += 34;
        if (parameter_key.find("dye") != std::string::npos || parameter_key.find("tint") != std::string::npos) score += 18;
        if (material_wrapper_matches_mesh_local_index(binding, mesh)) score += 210;
        if (binding.source_authority == "exact_sidecar") score += 90;
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    if (selected_score != nullptr) *selected_score = best == nullptr ? 0 : best_score;
    return best;
}

static bool binding_has_explicit_metalness_slot(const TextureBinding* binding) {
    if (binding == nullptr) return false;
    const std::string role = lower_copy(binding->role);
    const std::string semantic = lower_copy(binding->semantic_type + " " + binding->semantic_subtype);
    const std::string parameter_key = normalized_key(binding->parameter_name);
    if (role == "metalness") return true;
    if (semantic.find("metallic") != std::string::npos || semantic.find("metalness") != std::string::npos) return true;
    return (parameter_key.find("metallic") != std::string::npos || parameter_key.find("metalness") != std::string::npos)
        && parameter_key.find("colorblendingmask") == std::string::npos;
}

static bool evidence_contains_eye_surface_token(const std::string& evidence) {
    const std::string lower = lower_copy(evidence);
    return evidence_contains_token(lower, "eye")
        || evidence_contains_token(lower, "iris")
        || evidence_contains_token(lower, "pupil")
        || evidence_contains_token(lower, "cornea")
        || evidence_contains_token(lower, "eyeball")
        || lower.find("eyecover") != std::string::npos
        || lower.find("eyelid") != std::string::npos;
}

static bool evidence_contains_eye_cutout_surface_token(const std::string& evidence) {
    const std::string lower = lower_copy(evidence);
    return lower.find("eyecover") != std::string::npos
        || lower.find("eyelid") != std::string::npos;
}

static bool mesh_has_crimson_armor_equipment_surface(const NativeSubmesh& mesh) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return evidence.find("/armor/") != std::string::npos
        || evidence.find("/13_hel/") != std::string::npos
        || evidence.find("_hel_") != std::string::npos
        || evidence_contains_token(evidence, "helmet")
        || evidence_contains_token(evidence, "helm")
        || evidence_contains_token(evidence, "armor")
        || evidence_contains_token(evidence, "armour")
        || evidence_contains_token(evidence, "plate");
}

static bool mesh_has_crimson_weapon_surface(const NativeSubmesh& mesh) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return evidence.find("/weapon/") != std::string::npos
        || evidence.find("/2_twohandweapon/") != std::string::npos
        || evidence_contains_token(evidence, "weapon")
        || evidence_contains_token(evidence, "sword")
        || evidence_contains_token(evidence, "blade")
        || evidence_contains_token(evidence, "guard")
        || evidence_contains_token(evidence, "hilt")
        || evidence_contains_token(evidence, "pommel");
}

static bool mesh_local_surface_has_strong_nonmetal_token(const NativeSubmesh& mesh) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return evidence_contains_token(evidence, "cloth")
        || evidence_contains_token(evidence, "fabric")
        || evidence_contains_token(evidence, "flag")
        || evidence_contains_token(evidence, "banner")
        || evidence_contains_token(evidence, "tassel")
        || evidence_contains_token(evidence, "fringe")
        || evidence_contains_token(evidence, "ribbon")
        || evidence_contains_token(evidence, "sash")
        || evidence_contains_token(evidence, "rope")
        || evidence_contains_token(evidence, "uw")
        || evidence_contains_token(evidence, "underwear")
        || evidence_contains_token(evidence, "leather")
        || evidence_contains_token(evidence, "hide")
        || evidence_contains_token(evidence, "strap")
        || evidence_contains_token(evidence, "belt")
        || evidence_contains_token(evidence, "grip")
        || evidence_contains_token(evidence, "wrap")
        || evidence_contains_token(evidence, "handle")
        || evidence_contains_token(evidence, "wood")
        || evidence_contains_token(evidence, "stick")
        || evidence_contains_token(evidence, "shaft")
        || evidence_contains_token(evidence, "haft")
        || evidence_contains_token(evidence, "skin")
        || evidence_contains_token(evidence, "hair")
        || evidence_contains_token(evidence, "fur");
}

static bool texture_family_key_is_specific_material_response(const std::string& texture_family_key) {
    if (texture_family_key.empty()) return false;
    if (texture_family_key.find("texturelayer") != std::string::npos) return false;
    if (texture_family_key.find("common") != std::string::npos || texture_family_key.find("default") != std::string::npos) return false;
    if (texture_family_key.rfind("cd_temp", 0) == 0 || texture_family_key.find("temp") != std::string::npos) return false;
    return true;
}

static bool binding_has_authoritative_model_family_material_response(const TextureBinding* binding, const NativeSubmesh& mesh) {
    if (binding == nullptr) return false;
    if (binding_is_layer_selector_mask(*binding)) return false;
    const std::string role = lower_copy(binding->role);
    const std::string packed = lower_copy(binding->packed_channels);
    const bool sidecar_authoritative =
        binding->source_authority == "exact_sidecar"
        || (
            binding->material_output_quality == "exact"
            && (!binding->sidecar_path.empty() || !binding->parameter_declared_by.empty())
        );
    if (!sidecar_authoritative) return false;
    const bool material_response =
        role == "material"
        || role == "specular"
        || role == "roughness"
        || role == "metalness"
        || binding_has_explicit_metalness_slot(binding)
        || (
            packed.find("r=occlusion") != std::string::npos
            && packed.find("g=roughness") != std::string::npos
            && packed.find("b=metalness") != std::string::npos
        );
    if (!material_response) return false;

    const std::string texture_family_key = normalized_texture_family_key(
        binding->texture_name.empty() ? binding->archive_path : binding->texture_name
    );
    if (!texture_family_key_is_specific_material_response(texture_family_key)) return false;

    const std::vector<std::string> mesh_family_keys = {
        material_component_key_from_path(mesh.source_model_path),
        normalized_texture_family_key(mesh.source_component_label),
        normalized_material_key(mesh.material),
        normalized_material_key(mesh.name),
    };
    for (const std::string& mesh_family_key : mesh_family_keys) {
        if (material_keys_match_for_identity(texture_family_key, mesh_family_key)) return true;
    }
    return false;
}

static bool binding_has_authoritative_equipment_material_response(const TextureBinding* binding, const NativeSubmesh& mesh) {
    if (binding == nullptr) return false;
    if (binding_is_layer_selector_mask(*binding)) return false;
    if (!material_binding_matches_mesh_source(*binding, mesh)) return false;
    const std::string role = lower_copy(binding->role);
    const std::string parameter_key = normalized_key(binding->parameter_name);
    const std::string path_text = lower_copy(binding->archive_path + " " + binding->texture_name);
    const bool sidecar_authoritative =
        binding->source_authority == "exact_sidecar"
        || (
            binding->material_output_quality == "exact"
            && (!binding->sidecar_path.empty() || !binding->parameter_declared_by.empty())
        );
    if (!sidecar_authoritative) return false;
    const bool material_response =
        role == "material"
        || role == "specular"
        || role == "roughness"
        || role == "metalness"
        || binding_has_explicit_metalness_slot(binding)
        || path_text.find("_sp.dds") != std::string::npos;
    if (!material_response) return false;
    const std::string texture_family_key = normalized_texture_family_key(
        binding->texture_name.empty() ? binding->archive_path : binding->texture_name
    );
    if (!texture_family_key_is_specific_material_response(texture_family_key)) return false;
    if (material_wrapper_matches_mesh_local_index(*binding, mesh)) return true;
    return material_identity_match_score(*binding, mesh) >= 240;
}

static bool has_authoritative_model_family_material_response(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh
) {
    return std::any_of(bindings.begin(), bindings.end(), [&mesh](const TextureBinding* binding) {
        return binding_has_authoritative_model_family_material_response(binding, mesh);
    });
}

static bool has_authoritative_equipment_material_response(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh
) {
    return std::any_of(bindings.begin(), bindings.end(), [&mesh](const TextureBinding* binding) {
        return binding_has_authoritative_equipment_material_response(binding, mesh);
    });
}

static bool evidence_has_any_token(
    const std::string& evidence,
    std::initializer_list<const char*> tokens
) {
    return std::any_of(tokens.begin(), tokens.end(), [&evidence](const char* token) {
        return evidence_contains_token(evidence, token);
    });
}

// What the bound surface maps actually measure, when they can be read.
// `decoded` stays false for a submesh with no readable packed map, and the token
// rules below remain the only evidence in that case.
struct DecodedSurfaceEvidence {
    bool decoded = false;
    float metal_coverage = 0.0f;
    float mean_roughness = 0.0f;
};

// Crimson's packed maps put metal in blue. A dielectric map measures ~0.00
// coverage and a polished one ~1.00, so the middle band is a genuine mixed
// surface -- a blade with a leather grip, or a garment with metal studs.
static constexpr float kDecodedMetalDominantCoverage = 0.35f;
static constexpr float kDecodedMetalAbsentCoverage = 0.06f;

static bool binding_declares_readable_surface_response(const TextureBinding* binding) {
    if (binding == nullptr || binding->source_path.empty()) return false;
    if (binding_is_layer_selector_mask(*binding)) return false;
    if (binding->packed_channels.find("b=metalness") == std::string::npos) return false;
    // A shipped placeholder describes no asset. cd_temp_* stands in for unfinished
    // work and would otherwise be read as a real measurement.
    const std::string name = lower_copy(
        binding->texture_name.empty() ? binding->archive_path : binding->texture_name);
    return name.find("cd_temp") == std::string::npos;
}

static DecodedSurfaceEvidence decoded_surface_evidence(
    const std::vector<const TextureBinding*>& bindings,
    const TextureBinding* surface
) {
    // The submesh's own selected surface map answers for the whole submesh.
    if (binding_declares_readable_surface_response(surface)
        && lower_copy(surface->packed_channels).find("layer:") == std::string::npos) {
        const DdsChannelStatistics stats = inspect_dds_channel_statistics(surface->source_path);
        if (stats.valid) {
            DecodedSurfaceEvidence result;
            result.decoded = true;
            result.metal_coverage = stats.blue_coverage;
            result.mean_roughness = stats.mean_green;
            return result;
        }
    }
    // Otherwise the response only exists per colour layer, and which layer owns a
    // texel is decided by the colour-blending mask. That mask is readable too, and
    // its per-channel mean is how much of the surface each layer covers, so the
    // layers can be weighted by their own coverage instead of guessed at. Weighting
    // matters: an unweighted maximum let one metallic grime layer from the shared
    // tiling library declare a whole garment metal.
    DdsChannelStatistics mask;
    const TextureBinding* selector_mask = surface != nullptr
            && binding_is_layer_selector_mask(*surface)
        ? surface
        : nullptr;
    if (selector_mask == nullptr) {
        const auto found = std::find_if(bindings.begin(), bindings.end(), [](const TextureBinding* binding) {
            return binding != nullptr
                && !binding->source_path.empty()
                && binding_is_layer_selector_mask(*binding)
                && lower_copy(binding->packed_channels).find("layer:color_blending_mask") != std::string::npos;
        });
        if (found != bindings.end()) selector_mask = *found;
    }
    if (selector_mask != nullptr) {
        mask = inspect_dds_channel_statistics(selector_mask->source_path);
    }
    DecodedSurfaceEvidence result;
    int readable = 0;
    float lowest = 1.0f;
    float highest = 0.0f;
    float weight_total = 0.0f;
    float weighted_metal = 0.0f;
    float weighted_roughness = 0.0f;
    for (const TextureBinding* binding : bindings) {
        if (!binding_declares_readable_surface_response(binding)) continue;
        const DdsChannelStatistics stats = inspect_dds_channel_statistics(binding->source_path);
        if (!stats.valid) continue;
        ++readable;
        lowest = std::min(lowest, stats.blue_coverage);
        highest = std::max(highest, stats.blue_coverage);
        float weight = 1.0f;
        if (mask.valid) {
            const std::string channel = lower_copy(binding->layer_channel);
            weight = channel == "g" ? mask.mean_green
                : (channel == "b" ? mask.mean_blue : mask.mean_red);
        }
        weight = std::max(weight, 0.0f);
        weight_total += weight;
        weighted_metal += weight * stats.blue_coverage;
        weighted_roughness += weight * stats.mean_green;
    }
    if (readable == 0) return result;
    if (mask.valid && weight_total > 0.01f) {
        result.decoded = true;
        result.metal_coverage = weighted_metal / weight_total;
        result.mean_roughness = weighted_roughness / weight_total;
        return result;
    }
    // With no readable mask the layers speak only when they agree; layers that
    // disagree describe different materials and their average belongs to neither.
    if (highest >= kDecodedMetalAbsentCoverage && lowest < kDecodedMetalDominantCoverage) return result;
    result.decoded = true;
    result.metal_coverage = highest < kDecodedMetalAbsentCoverage ? highest : lowest;
    result.mean_roughness = weighted_roughness / std::max(1.0f, static_cast<float>(readable));
    return result;
}

struct MaterialCategoryEvidence {
    std::string local;
    std::string identity;
    std::string identity_shader;
    std::string all;
    bool cloth = false;
    bool leather_material = false;
    bool leather_part = false;
    bool leather = false;
    bool apparel_cloth_path = false;
    bool cloth_like = false;
    bool wood = false;
    bool glass = false;
    bool gem = false;
    bool stone = false;
    bool eye = false;
    bool tooth = false;
    bool bone = false;
    bool organic = false;
    bool foliage = false;
    bool hair_shader = false;
    bool equipment_surface = false;
    bool actual_hair = false;
    bool strong_skin = false;
    bool head_skin = false;
    bool strong_nonmetal = false;
};

static MaterialCategoryEvidence collect_material_category_evidence(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* base,
    const std::vector<MaterialLayer>& layers
) {
    MaterialCategoryEvidence result;
    result.local = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    // The part's own identity: its mesh names plus the albedo it actually shows.
    // Specialised families -- hair, skin, eye, tooth -- are read from this rather
    // than from every pooled binding path, because a support texture shared with
    // a neighbouring part is not evidence about this one. A `hair` token reaching
    // the pool this way classified a lacquered cuirass and a lace vest as hair.
    result.identity = result.local;
    if (base != nullptr) {
        result.identity += " " + lower_copy(base->archive_path + " " + base->texture_name + " " + base->parameter_name);
        result.identity_shader = lower_copy(base->shader_rule + " " + base->shader_family);
    }
    result.all = result.local;
    if (base != nullptr) {
        result.all += " " + lower_copy(base->archive_path + " " + base->texture_name + " " + base->parameter_name + " " + base->shader_rule + " " + base->shader_family);
    }
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        result.all += " " + lower_copy(binding->archive_path + " " + binding->texture_name + " "
            + binding->parameter_name + " " + binding->shader_rule + " " + binding->shader_family
            + " " + binding->material_parameter_names);
    }
    for (const MaterialLayer& layer : layers) {
        result.all += " " + lower_copy(layer.diffuse_archive_path + " " + layer.source_parameter + " " + layer.layer_role);
    }
    result.cloth = result.all.find("skinnedmeshcloth") != std::string::npos
        || evidence_has_any_token(result.all, {
            "cloth", "fabric", "flag", "banner", "vest", "tassel", "fringe", "ribbon", "sash",
            "rope", "uw", "underwear", "cloak", "cape", "skirt", "dress", "mantle", "robe", "flap"});
    result.leather_material = evidence_has_any_token(result.all, {"leather", "hide"});
    result.leather_part = evidence_has_any_token(result.all, {"strap", "belt", "grip", "wrap", "handle"});
    result.leather = result.leather_material || result.leather_part;
    const bool local_structural_metal = evidence_has_any_token(
        result.local, {"metal", "steel", "iron", "blade", "plate", "chain", "mail"});
    result.apparel_cloth_path = !local_structural_metal && !result.leather && (
        result.all.find("/9_upperbody/") != std::string::npos
        || result.all.find("/10_lowerbody/") != std::string::npos
        || result.all.find("_ub_") != std::string::npos
        || result.all.find("_lb_") != std::string::npos
        || evidence_has_any_token(result.all, {
            "upperbody", "lowerbody", "sleeve", "pants", "trouser", "shirt", "tunic"}));
    result.cloth_like = result.cloth || result.apparel_cloth_path;
    result.wood = evidence_has_any_token(result.all, {"wood", "timber", "plank", "stick", "shaft", "haft"});
    result.glass = evidence_has_any_token(result.all, {"glass", "crystal"});
    result.gem = evidence_has_any_token(result.all, {"gem", "jewel", "diamond", "ruby", "sapphire", "emerald"});
    result.stone = evidence_has_any_token(result.all, {"stone", "rock", "ceramic"});
    result.eye = evidence_contains_eye_surface_token(result.identity);
    result.tooth = evidence_has_any_token(result.identity, {"tooth", "teeth"});
    result.bone = evidence_has_any_token(result.identity, {"bone", "skull", "horn", "antler", "ivory"});
    result.organic = evidence_has_any_token(
        result.identity, {"organic", "flesh", "muscle", "organ", "tentacle", "membrane", "chitin"});
    result.foliage = evidence_has_any_token(
        result.identity, {"foliage", "leaf", "leaves", "grass", "moss", "plant", "flower"});
    // The declared family of the albedo this part actually shows, not of every
    // binding pooled onto it. A jacket that carries a fur collar contributes a
    // SkinnedMeshFur binding to the pool, and reading the pool made the cloth body
    // of that same jacket a hair surface.
    result.hair_shader = result.identity_shader.find("skinnedmeshhair") != std::string::npos
        || result.identity_shader.find("skinnedmeshfur") != std::string::npos
        || result.identity_shader.find("animalhair") != std::string::npos;
    result.equipment_surface = mesh_has_crimson_armor_equipment_surface(mesh)
        || evidence_has_any_token(result.all, {"helmet", "helm", "armor", "armour", "plate"});
    result.actual_hair = !result.equipment_surface
        && evidence_has_any_token(result.identity, {"hair", "fur", "beard", "brow", "eyebrow", "lash", "eyelash"});
    result.strong_skin = result.identity_shader.find("skinnedmeshskin") != std::string::npos
        || evidence_has_any_token(result.identity, {"skin", "nude", "body", "hand"});
    result.head_skin = evidence_contains_token(result.identity, "head") && !result.hair_shader && !result.actual_hair;
    result.strong_nonmetal = result.cloth_like || result.leather || result.wood || result.glass || result.gem
        || result.stone || result.eye || result.tooth || result.bone || result.organic || result.foliage
        || result.strong_skin || result.head_skin
        || result.hair_shader || result.actual_hair;
    return result;
}

static bool decoded_surface_promotes_metal(
    const DecodedSurfaceEvidence& decoded,
    const MaterialCategoryEvidence& evidence
) {
    return decoded.decoded
        && decoded.metal_coverage >= kDecodedMetalDominantCoverage
        && !evidence.strong_skin
        && !evidence.head_skin;
}

static bool material_category_has_metal(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const MaterialCategoryEvidence& evidence,
    const TextureBinding* surface
) {
    const bool strong_structural = evidence_has_any_token(
        evidence.all, {"metal", "steel", "iron", "blade", "plate"});
    const bool weak_equipment = evidence_has_any_token(
        evidence.all, {"guard", "hilt", "chain", "helmet", "helm", "armor", "armour"});
    const bool metal_color = evidence_has_any_token(
        evidence.all, {"gold", "silver", "copper", "bronze", "brass", "chrome"});
    const bool scalar_metal = std::any_of(bindings.begin(), bindings.end(), [](const TextureBinding* binding) {
        return binding != nullptr && binding_has_explicit_metalness_slot(binding);
    });
    const bool material_response_metal = std::any_of(bindings.begin(), bindings.end(), [](const TextureBinding* binding) {
        if (binding == nullptr) return false;
        const std::string role = lower_copy(binding->role + " " + binding->parameter_name + " " + binding->semantic_subtype);
        const bool response = role.find("material") != std::string::npos
            || role.find("specular") != std::string::npos
            || role.find("metal") != std::string::npos
            || binding_has_explicit_metalness_slot(binding);
        return response && binding->metalness_hint > 0.35f;
    });
    const bool local_handle = evidence_contains_token(evidence.local, "handle");
    const bool local_nonmetal_except_handle = evidence_has_any_token(evidence.local, {
        "cloth", "fabric", "uw", "underwear", "vest", "leather", "hide", "strap", "belt", "grip",
        "wrap", "wood", "stick", "shaft", "haft", "glass", "crystal", "gem", "jewel", "stone",
        "rock", "tooth", "teeth", "skin", "nude", "body", "hand", "hair", "fur", "brow",
        "eyebrow", "lash", "eyelash", "bone", "skull", "horn", "antler", "ivory", "organic",
        "flesh", "muscle", "organ", "tentacle", "membrane", "chitin", "foliage", "leaf", "leaves",
        "grass", "moss", "plant", "flower"})
        || evidence_contains_eye_surface_token(evidence.local)
        || evidence.apparel_cloth_path;
    const bool shield_handle_response = local_handle
        && evidence_contains_token(evidence.local, "shield")
        && mesh_has_crimson_weapon_surface(mesh)
        && has_authoritative_model_family_material_response(bindings, mesh)
        && material_response_metal
        && !local_nonmetal_except_handle
        && !evidence.leather_material && !evidence.cloth_like && !evidence.wood && !evidence.stone
        && !evidence.eye && !evidence.tooth && !evidence.bone && !evidence.organic && !evidence.foliage
        && !evidence.strong_skin && !evidence.head_skin && !evidence.actual_hair;
    const bool local_strong_nonmetal = local_nonmetal_except_handle || (local_handle && !shield_handle_response);
    const bool local_surface_nonmetal = (mesh_local_surface_has_strong_nonmetal_token(mesh) && !shield_handle_response)
        || evidence_has_any_token(evidence.local, {
            "uw", "underwear", "vest", "lb", "lowerbody", "jacket", "sleeve", "shirt", "tunic",
            "skirt", "dress", "pants", "trouser"});
    const bool local_metal = evidence_has_any_token(evidence.local, {
        "metal", "steel", "iron", "blade", "guard", "hilt", "pommel", "plate", "gold", "silver",
        "copper", "bronze", "brass", "chrome"}) && !local_strong_nonmetal;
    const bool armor_response = evidence.equipment_surface
        && has_authoritative_equipment_material_response(bindings, mesh)
        && !local_surface_nonmetal && !evidence.strong_skin && !evidence.head_skin && !evidence.wood
        && !evidence.stone && !evidence.eye && !evidence.tooth && !evidence.bone
        && !evidence.organic && !evidence.foliage;
    const bool weapon_response = mesh_has_crimson_weapon_surface(mesh)
        && has_authoritative_model_family_material_response(bindings, mesh)
        && (!local_strong_nonmetal || shield_handle_response)
        && (local_metal || scalar_metal || material_response_metal);
    // Where the surface map can be read it settles the question. The rules above
    // infer metal from the equipment slot a model occupies, which is a guess that
    // has to stand in for evidence -- and it is wrong for every soft item stored
    // beside plate. A map measuring no metal is positive evidence of a dielectric,
    // not merely the absence of evidence, so it withdraws the slot-based promotion
    // while leaving a name that actually says metal alone.
    const DecodedSurfaceEvidence decoded = decoded_surface_evidence(bindings, surface);
    if (decoded.decoded) {
        // The category names what the surface reads as overall. A minority metal
        // region -- the chape on a leather scabbard, studs on a garment -- keeps
        // its own metal because the shader honours the per-texel map, so a part
        // that is mostly leather stays leather rather than being called metal by
        // the equipment slot it happens to occupy.
        if (decoded_surface_promotes_metal(decoded, evidence)) return true;
        return local_metal || (strong_structural && !evidence.strong_nonmetal);
    }
    return local_metal || armor_response || weapon_response
        || (strong_structural && !evidence.strong_nonmetal)
        || ((metal_color || scalar_metal) && !evidence.strong_nonmetal)
        || (weak_equipment && scalar_metal && !evidence.strong_nonmetal);
}

static std::string material_category_for_bindings(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* base,
    const std::vector<MaterialLayer>& layers,
    const TextureBinding* surface
) {
    const MaterialCategoryEvidence evidence = collect_material_category_evidence(bindings, mesh, base, layers);
    if (evidence.eye) return "eye";
    if (evidence.tooth) return "tooth";
    if (evidence.bone) return "bone";
    if (evidence.organic) return "organic";
    if (evidence.foliage) return "foliage";
    if ((evidence.hair_shader || evidence.actual_hair) && (evidence.actual_hair || !evidence.strong_skin)) return "hair";
    if (material_category_has_metal(bindings, mesh, evidence, surface)) return "metal";
    if (evidence.cloth_like) return "cloth";
    if (evidence.leather) return "leather";
    if (evidence.wood) return "wood";
    if (evidence.glass) return "glass";
    if (evidence.gem) return "gem";
    if (evidence.stone) return "stone";
    if (base_binding_is_low_authority_overlay(base)
        && !(base != nullptr && binding_is_authoritative_same_family_overlay_base(*base, mesh))
        && evidence.all.find("shield") != std::string::npos) return "wood";
    if (evidence.strong_skin || evidence.head_skin) return "skin";
    return "generic";
}

static int native_material_category_code(const std::string& category) {
    const std::string value = lower_copy(category);
    if (value == "metal") return 1;
    if (value == "leather") return 2;
    if (value == "wood") return 3;
    if (value == "cloth") return 4;
    if (value == "skin") return 5;
    if (value == "hair") return 6;
    if (value == "glass") return 7;
    if (value == "gem") return 8;
    if (value == "stone") return 9;
    if (value == "eye") return 10;
    if (value == "tooth") return 11;
    if (value == "bone") return 12;
    if (value == "organic") return 13;
    if (value == "foliage") return 14;
    return 0;
}

static SurfaceProfile surface_profile_for_bindings(
    const std::string& category,
    const std::string& category_reason,
    float category_confidence,
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* base,
    const std::vector<MaterialLayer>& layers,
    const NativeMaterialHints& authored_hints
) {
    const MaterialCategoryEvidence source = collect_material_category_evidence(
        bindings, mesh, base, layers);
    SurfaceProfile profile;
    profile.family = category;
    profile.family_code = native_material_category_code(category);
    profile.confidence = std::clamp(category_confidence, 0.0f, 1.0f);
    profile.roughness_authored = authored_hints.roughness_authored;
    profile.metalness_authored = authored_hints.metalness_authored;
    profile.specular_authored = authored_hints.specular_authored;
    profile.height_scale_authored = authored_hints.height_scale_authored;

    const bool polished_token = evidence_has_any_token(
        source.all, {"polished", "gloss", "glossy", "mirror"});
    const bool satin_token = evidence_has_any_token(source.all, {"satin", "semigloss", "semi_gloss"});
    const bool matte_token = evidence_has_any_token(source.all, {"matte", "matt"});
    const bool rough_token = evidence_has_any_token(source.all, {"rough", "weathered", "rust", "grime"});
    if (polished_token) profile.finish = "polished";
    else if (satin_token) profile.finish = "satin";
    else if (matte_token) profile.finish = "matte";
    else if (rough_token) profile.finish = "rough";
    else if (category == "glass" || category == "gem" || category == "eye") profile.finish = "polished";
    else if (category == "metal" || category == "skin" || category == "hair" || category == "tooth"
        || category == "organic") profile.finish = "satin";
    else if (category == "leather" || category == "wood" || category == "bone") profile.finish = "matte";
    else if (category == "cloth" || category == "stone" || category == "foliage") profile.finish = "rough";

    if (category == "cloth") profile.structure = "woven";
    else if (category == "hair" || category == "foliage") profile.structure = "fibrous";
    else if (category == "wood" || category == "leather") profile.structure = "grained";
    else if (category == "skin" || category == "stone" || category == "bone") profile.structure = "porous";
    else if (category == "gem") profile.structure = "crystalline";
    else if (category == "organic") profile.structure = "shell";
    else if (category != "generic") profile.structure = "smooth";

    if (evidence_has_any_token(source.all, {"clearcoat", "clear_coat"})) profile.coating = "clearcoat";
    else if (evidence_has_any_token(source.all, {"lacquer", "lacquered"})) profile.coating = "lacquered";
    else if (evidence_has_any_token(source.all, {"paint", "painted", "coating"})) profile.coating = "painted";

    if (category == "metal") {
        profile.fallback_roughness = 0.30f;
        profile.fallback_metalness = 0.68f;
        profile.fallback_specular = 0.68f;
        profile.fallback_height_scale = 0.18f;
    } else if (category == "leather") {
        profile.fallback_roughness = 0.66f;
        profile.fallback_specular = 0.22f;
        profile.fallback_height_scale = 0.16f;
    } else if (category == "wood") {
        profile.fallback_roughness = 0.72f;
        profile.fallback_specular = 0.18f;
        profile.fallback_height_scale = 0.18f;
    } else if (category == "cloth") {
        profile.fallback_roughness = 0.84f;
        profile.fallback_specular = 0.055f;
        profile.fallback_height_scale = 0.12f;
    } else if (category == "skin") {
        profile.fallback_roughness = 0.56f;
        profile.fallback_specular = 0.20f;
        profile.fallback_height_scale = 0.10f;
    } else if (category == "hair") {
        profile.fallback_roughness = 0.58f;
        profile.fallback_specular = 0.22f;
        profile.fallback_height_scale = 0.08f;
        profile.fallback_anisotropy = 0.65f;
    } else if (category == "glass") {
        profile.fallback_roughness = 0.30f;
        profile.fallback_specular = 0.42f;
    } else if (category == "gem") {
        profile.fallback_roughness = 0.26f;
        profile.fallback_specular = 0.48f;
    } else if (category == "stone") {
        profile.fallback_roughness = 0.82f;
        profile.fallback_specular = 0.10f;
        profile.fallback_height_scale = 0.20f;
    } else if (category == "eye") {
        profile.fallback_roughness = 0.30f;
        profile.fallback_specular = 0.44f;
    } else if (category == "tooth") {
        profile.fallback_roughness = 0.58f;
        profile.fallback_specular = 0.18f;
    } else if (category == "bone") {
        profile.fallback_roughness = 0.68f;
        profile.fallback_specular = 0.16f;
        profile.fallback_height_scale = 0.14f;
    } else if (category == "organic") {
        profile.fallback_roughness = 0.62f;
        profile.fallback_specular = 0.18f;
        profile.fallback_height_scale = 0.12f;
    } else if (category == "foliage") {
        profile.fallback_roughness = 0.82f;
        profile.fallback_specular = 0.08f;
        profile.fallback_height_scale = 0.10f;
        profile.fallback_anisotropy = 0.35f;
    }

    if (profile.finish == "polished") profile.fallback_roughness = std::min(profile.fallback_roughness, 0.24f);
    else if (profile.finish == "satin") profile.fallback_roughness = std::clamp(profile.fallback_roughness, 0.34f, 0.62f);
    else if (profile.finish == "matte") profile.fallback_roughness = std::max(profile.fallback_roughness, 0.62f);
    else if (profile.finish == "rough") profile.fallback_roughness = std::max(profile.fallback_roughness, 0.78f);
    if (profile.coating == "clearcoat") {
        profile.fallback_roughness = std::min(profile.fallback_roughness, 0.18f);
        profile.fallback_specular = std::max(profile.fallback_specular, 0.45f);
    } else if (profile.coating == "lacquered") {
        profile.fallback_roughness = std::min(profile.fallback_roughness, 0.22f);
        profile.fallback_specular = std::max(profile.fallback_specular, 0.42f);
    }
    const bool explicit_profile_token = polished_token || satin_token || matte_token || rough_token
        || profile.coating != "none";
    if (explicit_profile_token) profile.confidence = std::min(1.0f, profile.confidence + 0.05f);
    profile.evidence = category_reason
        + (explicit_profile_token ? ";surface_profile=source_parameter_or_shader_token"
            : ";surface_profile=family_fallback");
    return profile;
}

static NativeMaterialHints resolve_surface_profile_fallbacks(
    NativeMaterialHints hints,
    SurfaceProfile& profile
) {
    if (!hints.roughness_authored) {
        hints.roughness = profile.fallback_roughness;
        profile.roughness_fallback_applied = true;
    }
    if (!hints.metalness_authored) {
        hints.metalness = profile.fallback_metalness;
        profile.metalness_fallback_applied = true;
    }
    if (!hints.specular_authored) {
        hints.specular = profile.fallback_specular;
        profile.specular_fallback_applied = true;
    }
    if (!hints.height_scale_authored) {
        hints.height_scale = profile.fallback_height_scale;
        profile.height_scale_fallback_applied = true;
    }
    profile.anisotropy_fallback_applied = profile.fallback_anisotropy > 0.0f;
    return hints;
}
