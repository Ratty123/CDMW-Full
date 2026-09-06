// A preview report shows why a candidate was dropped, so every pre-scoring
// rejection records one line naming the texture and the material it lost.
static void note_rejected_support_binding(
    std::vector<std::string>* rejected_examples,
    const std::string& desired_role,
    const std::string& reason,
    const TextureBinding& binding,
    const NativeSubmesh& mesh
) {
    if (rejected_examples == nullptr || rejected_examples->size() >= 16) return;
    rejected_examples->push_back(
        desired_role + " " + reason + " "
        + (binding.texture_name.empty() ? basename_from_path(binding.archive_path) : binding.texture_name)
        + " for " + mesh.material
    );
}

// cd_temp_* and the none/null/dummy family are unfinished authoring left in the
// shipped archive. Where a placeholder's absence is equivalent -- a flat normal,
// a neutral surface -- letting it stand in costs nothing, so it is only demoted
// and a real map outranks it.
//
// The colour-blending mask is deliberately excluded. There the same texture is a
// real instruction -- "layer R at 100%" -- that the game reads the same way, and
// 252 sampled assets that composite through it render correctly; rejecting it
// would make the preview less faithful, not more.
static bool binding_is_placeholder_support_texture(
    const TextureBinding& binding,
    const std::string& desired_role
) {
    return desired_role != "material"
        && (placeholder_layer_mask_path(binding.archive_path)
            || placeholder_layer_mask_path(binding.texture_name));
}

// Candidates that must not be scored at all, as opposed to merely demoted.
static bool support_binding_rejected_before_scoring(
    const TextureBinding& binding,
    const NativeSubmesh& mesh,
    const std::string& desired_role,
    bool placeholder_support_texture,
    std::vector<std::string>* rejected_examples
) {
    // Wrapper order says which of a model's materials a submesh uses. It is not a
    // claim that a material's own maps belong to one submesh only: a model can
    // bind the same material to several submeshes, and then only the one whose
    // local index happens to equal the wrapper index accepted its normal and
    // surface maps while the rest rendered flat. On cd_phm_00_bag_0035,
    // CD_PHM_04_String_0001 is used by four submeshes and exactly one got its
    // maps. Where the binding names the same material the mesh declares, identity
    // is already established and wrapper order has nothing left to disambiguate.
    const bool binding_declares_mesh_material =
        !normalized_material_key(binding.material_name).empty()
        && material_keys_match_for_identity(
            normalized_material_key(binding.material_name),
            normalized_material_key(mesh.material));
    if (
        binding.material_wrapper_order_authoritative
        && binding.material_wrapper_index >= 0
        && mesh.source_local_submesh_index >= 0
        && binding.material_wrapper_index != mesh.source_local_submesh_index
        && !binding_declares_mesh_material
    ) {
        note_rejected_support_binding(rejected_examples, desired_role, "rejected cross-wrapper candidate", binding, mesh);
        return true;
    }
    // A placeholder that would *create* an effect the part does not otherwise
    // have must not be used at all: cd_temp_r_m.dds decodes to (1, 0, 0), so as an
    // emissive map it makes a part glow and as a height map its R drives maximum
    // displacement across the whole surface.
    if (placeholder_support_texture
        && (desired_role == "emissive" || desired_role == "height")) {
        note_rejected_support_binding(rejected_examples, desired_role, "rejected placeholder candidate", binding, mesh);
        return true;
    }
    if (binding_is_skin_detail_support(binding) && desired_role != "detail") {
        // Skin detail normal/response textures tile through their authored mask.
        // They must not also occupy a whole-surface normal or specular slot.
        note_rejected_support_binding(
            rejected_examples,
            desired_role,
            "rejected support-only skin detail candidate",
            binding,
            mesh);
        return true;
    }
    if (desired_role == "material" && binding_is_layer_selector_mask(binding)) {
        // The binding is still present in the complete binding set, where
        // compile_material_layers uses it as the mask for the corresponding
        // `_sp` layer.  Only global material-response selection rejects it.
        note_rejected_support_binding(
            rejected_examples,
            desired_role,
            "rejected layer-selector mask candidate",
            binding,
            mesh);
        return true;
    }
    const std::string layer_role = lower_copy(binding.layer_role);
    const bool layer_scoped_response =
        layer_role == "damage" || layer_role == "detail"
        || layer_role == "grime" || layer_role == "dye"
        || layer_role == "overlay" || layer_role == "layer"
        || lower_copy(binding.packed_channels).find("layer:") != std::string::npos;
    if ((desired_role == "material" || desired_role == "specular")
        && layer_scoped_response) {
        // The full Rust path composites this response through the exact layer
        // mask. Publishing it as a direct whole-material slot at the same time
        // paints that layer over every texel and defeats the graph.
        note_rejected_support_binding(
            rejected_examples,
            desired_role,
            "rejected layer-only material-response candidate",
            binding,
            mesh);
        return true;
    }
    if (desired_role == "height"
        && (layer_role == "damage" || layer_role == "detail"
            || layer_role == "grime" || layer_role == "layer")) {
        // Detail relief is evaluated through the material-layer graph and its
        // mask. Promoting the same tiling layer to the global height slot paints
        // it over the whole part; nude head/body then inherit the generic
        // cd_texturelayer displacement even though only the hand declares a
        // true _heightTexture.
        note_rejected_support_binding(
            rejected_examples,
            desired_role,
            "rejected layer-only height candidate",
            binding,
            mesh);
        return true;
    }
    return false;
}

static const TextureBinding* best_binding_for_role(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const std::string& desired_role,
    int* selected_score = nullptr,
    std::vector<std::string>* rejected_examples = nullptr
) {
    const TextureBinding* best = nullptr;
    int best_score = desired_role == "base" ? 40 : 20;
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        if (binding.role != desired_role) {
            continue;
        }
        const bool placeholder_support_texture =
            binding_is_placeholder_support_texture(binding, desired_role);
        if (support_binding_rejected_before_scoring(
                binding, mesh, desired_role, placeholder_support_texture, rejected_examples)) {
            continue;
        }
        if (support_role_requires_material_scope(desired_role) && !material_binding_matches_mesh_source(binding, mesh)) {
            if (rejected_examples != nullptr && rejected_examples->size() < 16) {
                rejected_examples->push_back(
                    desired_role + " rejected cross-component candidate "
                    + (binding.texture_name.empty() ? basename_from_path(binding.archive_path) : binding.texture_name)
                    + " for " + mesh.material
                    + " sidecar=" + basename_from_path(binding.sidecar_path)
                    + " source=" + basename_from_path(mesh.source_model_path)
                );
            }
            continue;
        }
        const int identity_score = material_identity_match_score(binding, mesh);
        const int identity_threshold = support_role_requires_material_scope(desired_role)
            ? support_role_identity_threshold(desired_role)
            : 0;
        const std::string texture_family_key = normalized_texture_family_key(binding.texture_name.empty() ? binding.archive_path : binding.texture_name);
        const bool authoritative_wrapper_match = material_wrapper_matches_mesh_local_index(binding, mesh);
        const bool conflicting_specific_part = support_role_requires_material_scope(desired_role)
            && !authoritative_wrapper_match
            && material_identity_has_conflicting_specific_part(
                texture_family_key,
                normalized_material_key(mesh.material),
                normalized_material_key(mesh.name));
        if (
            (material_identity_requires_exact_path_match(binding, mesh) && identity_score < 120)
            || (identity_threshold > 0 && identity_score > 0 && identity_score < identity_threshold)
            || (identity_threshold > 0 && !normalized_material_key(binding.material_name).empty() && identity_score <= 0)
            || conflicting_specific_part
        ) {
            if (rejected_examples != nullptr && rejected_examples->size() < 16) {
                rejected_examples->push_back(
                    desired_role + (conflicting_specific_part ? " rejected cross-part candidate " : " rejected cross-slot candidate ")
                    + (binding.texture_name.empty() ? basename_from_path(binding.archive_path) : binding.texture_name)
                    + " for " + mesh.material
                    + " identity=" + std::to_string(identity_score)
                );
            }
            continue;
        }
        int score = material_match_score(binding, mesh, desired_role);
        score += identity_score / 2;
        // A real map of any provenance outranks unfinished authoring.
        if (placeholder_support_texture) score -= 400;
        const std::string parameter_key = normalized_key(binding.parameter_name);
        const std::string layer_role = lower_copy(binding.layer_role);
        if (desired_role == "normal") {
            if (parameter_key.find("normaltexture") != std::string::npos && layer_role != "damage" && layer_role != "detail" && layer_role != "grime") {
                score += 140;
            }
            if (layer_role == "damage" || layer_role == "detail" || layer_role == "grime") {
                score -= 170;
            }
        }
        if (desired_role == "material" || desired_role == "specular") {
            if (parameter_key.find("materialtexture") != std::string::npos && layer_role != "damage" && layer_role != "detail" && layer_role != "grime") {
                score += 140;
            }
            // A layer-named parameter can still hold the surface's own map. On
            // SkinnedMeshStandard garments the unsuffixed _detailMaterialMask
            // points at <mesh>_sp.dds -- the same family as the base albedo --
            // while the channel-suffixed _detailMaterialMask{R,G,B} point at the
            // shared cd_texturelayer_* tiling library. Penalising both alike gave
            // the material slot to _colorBlendingMaskTexture, which selects a
            // colour layer and carries no surface response, so the garment ended
            // up with no roughness or metal at all. Stay below the +140 an
            // authored _materialTexture earns so a real one still wins.
            const bool own_family_material_response =
                (layer_role == "damage" || layer_role == "detail" || layer_role == "grime")
                && binding.packed_channels.rfind("layer:material_response", 0) == 0
                && texture_family_key.find("texturelayer") == std::string::npos
                && base_binding_texture_family_matches_mesh(binding, mesh);
            if (own_family_material_response) {
                score += 120;
            } else if (layer_role == "damage" || layer_role == "detail" || layer_role == "grime") {
                score -= 190;
            }
        }
        if (desired_role == "height") {
            if (parameter_key.find("heighttexture") != std::string::npos && layer_role != "damage" && layer_role != "detail" && layer_role != "grime") {
                score += 140;
            }
            if (layer_role == "damage" || layer_role == "detail" || layer_role == "grime") {
                score -= 170;
            }
        }
        if (binding.material_wrapper_order_authoritative && binding.material_wrapper_index >= 0 && mesh.source_local_submesh_index >= 0) {
            if (binding.material_wrapper_index == mesh.source_local_submesh_index) {
                score += 180;
            } else {
                score -= 48;
            }
        }
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    if (selected_score != nullptr) *selected_score = best == nullptr ? 0 : best_score;
    return best;
}

struct BaseBindingAvailability {
    bool authoritative_sidecar = false;
    bool non_low_authority_visible = false;
    bool mesh_family_visible = false;
    // The part binds a primary base colour of its own texture family -- the
    // thing an overlay is painted on top of, not a substitute for it.
    bool same_family_primary_base = false;
};

static bool mesh_binds_its_own_primary_base_color(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh
) {
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty() || binding.role != "base") continue;
        if (placeholder_visible_base_path(binding.archive_path) || placeholder_visible_base_path(binding.texture_name)) continue;
        if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)
            || dds_format_is_data_only_for_visible_base(binding.dds_format)) continue;
        if (!material_binding_matches_mesh_source(binding, mesh)) continue;
        if (!binding_is_primary_apparel_base_color(binding)) continue;
        if (base_binding_is_wrong_family_layer_or_environment(binding, mesh)) continue;
        if (!base_binding_texture_family_matches_mesh(binding, mesh)) continue;
        return true;
    }
    return false;
}

static BaseBindingAvailability inspect_base_binding_availability(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh
) {
    BaseBindingAvailability availability;
    availability.same_family_primary_base = mesh_binds_its_own_primary_base_color(bindings, mesh);
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty() || binding.role != "base") continue;
        if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)
            || dds_format_is_data_only_for_visible_base(binding.dds_format)) continue;
        if (!material_binding_matches_mesh_source(binding, mesh)) continue;
        const int identity_score = material_identity_match_score(binding, mesh);
        const std::string texture_family_key = normalized_texture_family_key(binding.texture_name.empty() ? binding.archive_path : binding.texture_name);
        const bool wrapper_match = material_wrapper_matches_mesh_local_index(binding, mesh);
        if (base_binding_has_unsafe_cross_part_texture_family(binding, mesh)) continue;
        if (!wrapper_match && material_identity_has_conflicting_specific_part(
            texture_family_key, normalized_material_key(mesh.material), normalized_material_key(mesh.name))) continue;
        const bool authoritative_visible = parameter_is_authoritative_visible_base(binding.parameter_name)
            || binding.visible_class == "primary_visible";
        const bool authoritative_wrapper = authoritative_wrapper_visible_base_for_mesh(binding, mesh);
        const bool mesh_family = base_binding_texture_family_matches_mesh(binding, mesh);
        const bool same_family_overlay = binding_is_authoritative_same_family_overlay_base(binding, mesh);
        const bool low_authority = base_binding_is_low_authority_overlay(&binding) && !same_family_overlay;
        const bool wrong_family = base_binding_is_wrong_family_layer_or_environment(binding, mesh);
        if (mesh_family && !low_authority && !wrong_family) availability.mesh_family_visible = true;
        if (!authoritative_wrapper && low_authority && !(authoritative_visible && identity_score >= 120)) continue;
        if ((authoritative_wrapper && !wrong_family)
            || (binding.source_authority == "exact_sidecar" && identity_score >= 300 && authoritative_visible && !wrong_family)) {
            availability.authoritative_sidecar = true;
        }
        const bool stable_visible = binding.source_authority == "embedded_mesh"
            || binding.visible_class == "primary_visible"
            || (authoritative_visible && !base_binding_is_low_authority_overlay(&binding));
        if (identity_score >= 120 && !wrong_family
            && (stable_visible || binding.visible_class == "layer_visible" || mesh_family)) {
            availability.non_low_authority_visible = true;
            break;
        }
    }
    return availability;
}

static const TextureBinding* best_base_binding_for_mode(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const EntryJob& job,
    int* selected_score = nullptr,
    std::vector<std::string>* rejected_examples = nullptr
) {
    const std::string mode = normalize_visible_texture_mode(job.visible_texture_mode);
    const BaseBindingAvailability availability = inspect_base_binding_availability(bindings, mesh);
    const TextureBinding* best = nullptr;
    int best_score = 40;
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty() || binding.role != "base") continue;
        if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)
            || dds_format_is_data_only_for_visible_base(binding.dds_format)) continue;
        if (!material_binding_matches_mesh_source(binding, mesh)) continue;
        const int identity_score = material_identity_match_score(binding, mesh);
        const std::string texture_family_key = normalized_texture_family_key(binding.texture_name.empty() ? binding.archive_path : binding.texture_name);
        const bool embedded = binding.source_authority == "embedded_mesh";
        const bool authoritative_wrapper_match = material_wrapper_matches_mesh_local_index(binding, mesh);
        if (base_binding_has_unsafe_cross_part_texture_family(binding, mesh)) {
            append_rejected_binding_example(rejected_examples, "base", "cross-part", binding, mesh, identity_score);
            continue;
        }
        if (!authoritative_wrapper_match && material_identity_has_conflicting_specific_part(
            texture_family_key,
            normalized_material_key(mesh.material),
            normalized_material_key(mesh.name))) {
            append_rejected_binding_example(rejected_examples, "base", "cross-part", binding, mesh, identity_score);
            continue;
        }
        // The support roles already exempt a binding that names the mesh's own
        // material; base did not, so a second submesh sharing one material kept
        // its normal and surface maps but lost its albedo and fell back to a flat
        // material tint. cd_phm_02_sword_0013 binds cd_phm_02_acc_0032 to two
        // accessory submeshes and only the first was rendering its texture.
        if (
            binding.material_wrapper_order_authoritative
            && binding.material_wrapper_index >= 0
            && mesh.source_local_submesh_index >= 0
            && binding.material_wrapper_index != mesh.source_local_submesh_index
            && !binding_texture_family_is_mesh_material(binding, mesh)
        ) {
            continue;
        }
        if (binding.material_wrapper_order_authoritative && identity_score < 120) {
            continue;
        }
        const bool authoritative_visible_base = parameter_is_authoritative_visible_base(binding.parameter_name);
        const bool layer_diffuse_candidate =
            !authoritative_visible_base
            && base_binding_is_layer_albedo_candidate(binding);
        const bool mesh_family_visible_base = base_binding_texture_family_matches_mesh(binding, mesh);
        const bool same_family_overlay_base = binding_is_authoritative_same_family_overlay_base(binding, mesh);
        const bool apparel_slot_surface = mesh_has_apparel_slot_surface_for_base_selection(mesh);
        const bool low_authority = base_binding_is_low_authority_overlay(&binding) && !same_family_overlay_base;
        const bool wrong_family_layer_base = base_binding_is_wrong_family_layer_or_environment(binding, mesh);
        if (!embedded && !normalized_material_key(binding.material_name).empty() && identity_score <= 0) {
            continue;
        }
        if (embedded && availability.authoritative_sidecar) {
            continue;
        }
        if (
            low_authority
            && availability.non_low_authority_visible
            && !(authoritative_visible_base && identity_score >= 120 && binding.visible_class != "visible_generic")
        ) {
            continue;
        }
        if (mode == "mesh_base_first" && wrong_family_layer_base && availability.mesh_family_visible && !embedded) {
            append_rejected_binding_example(rejected_examples, "base", "wrong-family-layer", binding, mesh, identity_score);
            continue;
        }
        if (mode == "mesh_base_first" && layer_diffuse_candidate && !mesh_family_visible_base && (availability.non_low_authority_visible || availability.authoritative_sidecar) && !embedded) {
            continue;
        }
        if (!embedded && !visible_class_allowed_for_mode(mode, binding.visible_class)) {
            const bool allow_authoritative_mesh_base =
                mode == "mesh_base_first"
                && authoritative_visible_base
                && identity_score >= 120;
            if (!allow_authoritative_mesh_base && !(mode == "mesh_base_first" && binding.visible_class == "visible_generic" && !availability.non_low_authority_visible)) {
                continue;
            }
        }
        const std::string parameter_key = normalized_key(binding.parameter_name);
        int score = material_match_score(binding, mesh, "base");
        score += visible_class_priority(binding.visible_class) * 18;
        if (mesh_family_visible_base) score += 190;
        // An `_overlayColorTexture` is dirt, wear or a paint pass laid over a
        // part's own colour, not the colour itself. It used to outrank the real
        // base by 260 unless the part looked like a torso or legs, and that
        // slot list never covered gloves, hoods, boots, bags or rings -- so
        // across 3,148 sampled parts 223 rendered an `_o` overlay as their
        // albedo, every one of them with its own `_baseColorTexture` bound
        // alongside. The slot list was a proxy for the real question, which is
        // whether the part supplies a primary base colour of its own family.
        const bool overlay_would_replace_real_base =
            apparel_slot_surface || availability.same_family_primary_base;
        if (same_family_overlay_base) score += overlay_would_replace_real_base ? -120 : 260;
        if (apparel_slot_surface && binding_is_primary_apparel_base_color(binding)) score += 180;
        if (wrong_family_layer_base) score -= 320;
        if (authoritative_visible_base && identity_score >= 120) score += 155;
        if (authoritative_wrapper_match) score += 210;
        if (binding.source_authority == "exact_sidecar" && binding.material_wrapper_order_authoritative && identity_score >= 300) score += 260;
        if (embedded) score += mode == "sidecar_visible_first" ? 20 : 120;
        if (binding.source_authority == "exact_sidecar") score += mode == "sidecar_visible_first" ? 95 : 55;
        if (mode == "mesh_base_first") {
            if (!embedded && binding.visible_class == "primary_visible") score += 75;
            if (!embedded && binding.visible_class == "layer_visible") {
                score += 34;
                if (parameter_key.find("detaildiffuse") != std::string::npos || parameter_key.find("detailcol") != std::string::npos) score += 44;
                if (parameter_key.find("grimediffuse") != std::string::npos) score += 18;
            }
            if (!embedded && binding.visible_class == "visible_generic") score -= 54;
            if (low_authority) {
                score -= 220;
            }
        } else if (mode == "layer_aware_visible") {
            if (binding.visible_class == "layer_visible") score += 35;
            if (parameter_key.find("detaildiffuse") != std::string::npos) score += 24;
            if (low_authority) score -= 140;
        } else if (mode == "sidecar_visible_first") {
            if (!embedded) score += 65;
            if (binding.visible_class == "layer_visible") score += 22;
            if (parameter_key.find("detaildiffuse") != std::string::npos) score += 18;
            if (low_authority) score -= 120;
        }
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    int overlay_score = 0;
    if (const TextureBinding* overlay_base = best_overlay_base_fallback(bindings, mesh, &overlay_score)) {
        if (best == nullptr || selected_base_should_yield_to_overlay(best, *overlay_base, mesh, best_score, overlay_score)) {
            best = overlay_base;
            best_score = overlay_score;
        }
    }
    if (selected_score != nullptr) *selected_score = best == nullptr ? 0 : best_score;
    return best;
}

static std::string shader_rule_for_family(const std::string& family) {
    const std::string lower = lower_copy(family);
    if (lower.find("skinnedmeshskin") != std::string::npos) return "skin";
    if (lower.find("skinnedmeshcloth_ver2") != std::string::npos) return "cloth_v2";
    if (lower.find("skinnedmeshcloth") != std::string::npos) return "cloth";
    if (lower.find("skinnedmeshstandard_ver2") != std::string::npos) return "standard_v2";
    if (lower.find("skinnedmeshstandard") != std::string::npos) return "standard";
    if (lower.find("skinnedmeshhair") != std::string::npos || lower.find("skinnedmeshfur") != std::string::npos || lower.find("animalhair") != std::string::npos) return "hair";
    // SkinnedMeshTear is a decal shell laid over a head. It declares a normal, a
    // surface map and an `_m` atlas whose R, G and B are three selectable tear
    // shapes; it has no colour of its own -- the tears take the skin beneath.
    if (lower.find("skinnedmeshtear") != std::string::npos) return "tear";
    if (lower.find("emissive") != std::string::npos) return "emissive";
    if (lower.find("multitextured") != std::string::npos) return "static_multitextured";
    if (lower.find("standard") != std::string::npos) return "static_standard";
    return "generic";
}

struct SidecarParameterSummary {
    int texture_params = 0;
    int float_params = 0;
    int color_params = 0;
    int byte4_params = 0;
    int bit_flags = 0;
    std::string linked_mesh_path;
};

static int regex_count(const std::string& text, const std::regex& pattern) {
    return static_cast<int>(std::distance(std::sregex_iterator(text.begin(), text.end(), pattern), std::sregex_iterator()));
}

static SidecarParameterSummary summarize_sidecar_parameters(const std::string& text) {
    SidecarParameterSummary summary;
    summary.texture_params = regex_count(text, std::regex("MaterialParameterTexture", std::regex_constants::icase));
    summary.float_params = regex_count(text, std::regex("MaterialParameterFloat|<FloatParameter|_float", std::regex_constants::icase));
    summary.color_params = regex_count(text, std::regex("MaterialParameterColor|ColorParameter|Tint|_color", std::regex_constants::icase));
    summary.byte4_params = regex_count(text, std::regex("MaterialParameterByte4|Byte4", std::regex_constants::icase));
    summary.bit_flags = regex_count(text, std::regex("BitFlag|MaterialBit|_flag", std::regex_constants::icase));
    const std::regex linked_mesh_pattern("([A-Za-z0-9_./\\\\-]+\\.(?:pac|pam|pamlod))", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(text, match, linked_mesh_pattern)) {
        summary.linked_mesh_path = match[1].str();
        std::replace(summary.linked_mesh_path.begin(), summary.linked_mesh_path.end(), '\\', '/');
    }
    return summary;
}

struct ParsedMaterialSidecar {
    std::string shader_family;
    std::string shader_rule;
    SidecarParameterSummary parameter_summary;
    std::vector<SidecarTextureRef> refs;
    std::vector<MaterialWrapperDeclaration> declarations;
    std::vector<NativePbdSidecarHint> pbd_hints;
    int material_wrapper_count = 0;
};

static std::uint64_t g_sidecar_parse_cache_hits = 0;
static std::uint64_t g_sidecar_parse_cache_misses = 0;
