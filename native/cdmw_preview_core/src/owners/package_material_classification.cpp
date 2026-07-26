
struct NativeMaterialHints {
    float roughness = 0.45f;
    float metalness = 0.0f;
    float specular = 0.45f;
    float height_scale = 0.35f;
};

static NativeMaterialHints clamp_material_hints_for_category(NativeMaterialHints hints, const std::string& category) {
    const std::string normalized = lower_copy(category);
    if (normalized == "cloth") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.28f);
        hints.roughness = std::max(hints.roughness, 0.48f);
    } else if (normalized == "leather") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.36f);
        hints.roughness = std::max(hints.roughness, 0.38f);
    } else if (normalized == "wood") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.30f);
        hints.roughness = std::max(hints.roughness, 0.44f);
    } else if (normalized == "skin") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.34f);
        hints.roughness = std::max(hints.roughness, 0.30f);
    } else if (normalized == "hair") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.46f);
        hints.roughness = std::max(hints.roughness, 0.36f);
    } else if (normalized == "stone") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.24f);
        hints.roughness = std::max(hints.roughness, 0.58f);
    } else if (normalized == "tooth") {
        hints.metalness = 0.0f;
        hints.specular = std::min(hints.specular, 0.26f);
        hints.roughness = std::max(hints.roughness, 0.42f);
    }
    return hints;
}

static NativeMaterialHints material_hints_for_bindings(const std::vector<const TextureBinding*>& bindings) {
    NativeMaterialHints hints;
    bool has_skin = false;
    bool has_hair = false;
    bool has_standard_v2 = false;
    bool has_static_multi = false;
    bool has_specular = false;
    bool has_material_mask = false;
    bool has_height = false;
    bool has_metal = false;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string rule = lower_copy(binding->shader_rule);
        const std::string packed = lower_copy(binding->packed_channels + " " + binding->parameter_name);
        has_skin = has_skin || rule == "skin";
        has_hair = has_hair || rule == "hair";
        has_standard_v2 = has_standard_v2 || rule == "standard_v2";
        has_static_multi = has_static_multi || rule == "static_multitextured";
        has_specular = has_specular || binding->role == "specular";
        has_material_mask = has_material_mask || binding->role == "material" || binding->role == "detail";
        has_height = has_height || binding->role == "height";
        has_metal = has_metal || packed.find("metal") != std::string::npos;
        roughness_hint = std::max(roughness_hint, binding->roughness_hint);
        metalness_hint = std::max(metalness_hint, binding->metalness_hint);
        specular_hint = std::max(specular_hint, binding->specular_hint);
        height_scale_hint = std::max(height_scale_hint, binding->height_scale_hint);
    }
    if (has_skin) {
        hints.roughness = 0.56f;
        hints.specular = 0.28f;
        hints.height_scale = 0.18f;
    } else if (has_hair) {
        hints.roughness = 0.38f;
        hints.specular = 0.58f;
        hints.height_scale = 0.14f;
    } else if (has_standard_v2) {
        hints.roughness = has_material_mask ? 0.42f : 0.50f;
        hints.specular = has_specular ? 0.56f : 0.38f;
        hints.metalness = has_metal ? 0.10f : 0.0f;
        hints.height_scale = has_height ? 0.34f : 0.0f;
    } else if (has_static_multi) {
        hints.roughness = 0.58f;
        hints.specular = has_specular ? 0.30f : 0.18f;
        hints.height_scale = has_height ? 0.24f : 0.0f;
    } else {
        hints.specular = has_specular ? 0.42f : 0.20f;
        hints.height_scale = has_height ? 0.28f : 0.0f;
    }
    if (roughness_hint > 0.0f) hints.roughness = std::clamp(roughness_hint, 0.04f, 0.96f);
    if (metalness_hint > 0.0f) hints.metalness = std::clamp(metalness_hint, 0.0f, 1.0f);
    if (specular_hint > 0.0f) hints.specular = std::clamp(specular_hint, 0.0f, 1.0f);
    if (height_scale_hint > 0.0f) hints.height_scale = std::clamp(height_scale_hint, 0.0f, 1.0f);
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

static bool shader_rule_supports_conservative_layer_stack(const std::vector<const TextureBinding*>& bindings) {
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
    const std::string role = lower_copy(binding->role);
    const std::string parameter_key = normalized_key(binding->parameter_name);
    const std::string path_text = lower_copy(binding->archive_path + " " + binding->texture_name);
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
            parameter_key == "colorblendingmasktexture"
            && path_text.find("_ma") != std::string::npos
        )
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
        || path_text.find("_ma.dds") != std::string::npos
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

struct MaterialCategoryEvidence {
    std::string local;
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
    result.all = result.local;
    if (base != nullptr) {
        result.all += " " + lower_copy(base->archive_path + " " + base->texture_name + " " + base->parameter_name + " " + base->shader_rule + " " + base->shader_family);
    }
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        result.all += " " + lower_copy(binding->archive_path + " " + binding->texture_name + " " + binding->parameter_name + " " + binding->shader_rule + " " + binding->shader_family);
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
    result.eye = evidence_contains_eye_surface_token(result.all);
    result.tooth = evidence_has_any_token(result.all, {"tooth", "teeth"});
    result.hair_shader = result.all.find("skinnedmeshhair") != std::string::npos
        || result.all.find("skinnedmeshfur") != std::string::npos
        || result.all.find("animalhair") != std::string::npos;
    result.equipment_surface = mesh_has_crimson_armor_equipment_surface(mesh)
        || evidence_has_any_token(result.all, {"helmet", "helm", "armor", "armour", "plate"});
    result.actual_hair = !result.equipment_surface
        && evidence_has_any_token(result.all, {"hair", "fur", "beard", "brow", "eyebrow", "lash", "eyelash"});
    result.strong_skin = result.all.find("skinnedmeshskin") != std::string::npos
        || evidence_has_any_token(result.all, {"skin", "nude", "body", "hand"});
    result.head_skin = evidence_contains_token(result.all, "head") && !result.hair_shader && !result.actual_hair;
    result.strong_nonmetal = result.cloth_like || result.leather || result.wood || result.glass || result.gem
        || result.stone || result.eye || result.tooth || result.strong_skin || result.head_skin
        || result.hair_shader || result.actual_hair;
    return result;
}

static bool material_category_has_metal(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const MaterialCategoryEvidence& evidence
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
        "eyebrow", "lash", "eyelash"})
        || evidence_contains_eye_surface_token(evidence.local)
        || evidence.apparel_cloth_path;
    const bool shield_handle_response = local_handle
        && evidence_contains_token(evidence.local, "shield")
        && mesh_has_crimson_weapon_surface(mesh)
        && has_authoritative_model_family_material_response(bindings, mesh)
        && material_response_metal
        && !local_nonmetal_except_handle
        && !evidence.leather_material && !evidence.cloth_like && !evidence.wood && !evidence.stone
        && !evidence.eye && !evidence.tooth && !evidence.strong_skin && !evidence.head_skin && !evidence.actual_hair;
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
        && !evidence.stone && !evidence.eye && !evidence.tooth;
    const bool weapon_response = mesh_has_crimson_weapon_surface(mesh)
        && has_authoritative_model_family_material_response(bindings, mesh)
        && (!local_strong_nonmetal || shield_handle_response)
        && (local_metal || scalar_metal || material_response_metal);
    return local_metal || armor_response || weapon_response
        || (strong_structural && !evidence.strong_nonmetal)
        || ((metal_color || scalar_metal) && !evidence.strong_nonmetal)
        || (weak_equipment && scalar_metal && !evidence.strong_nonmetal);
}

static std::string material_category_for_bindings(
    const std::vector<const TextureBinding*>& bindings,
    const NativeSubmesh& mesh,
    const TextureBinding* base,
    const std::vector<MaterialLayer>& layers
) {
    const MaterialCategoryEvidence evidence = collect_material_category_evidence(bindings, mesh, base, layers);
    if (evidence.eye) return "eye";
    if (evidence.tooth) return "tooth";
    if ((evidence.hair_shader || evidence.actual_hair) && (evidence.actual_hair || !evidence.strong_skin)) return "hair";
    if (material_category_has_metal(bindings, mesh, evidence)) return "metal";
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
