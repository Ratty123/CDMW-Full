
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
        if (
            binding.material_wrapper_order_authoritative
            && binding.material_wrapper_index >= 0
            && mesh.source_local_submesh_index >= 0
            && binding.material_wrapper_index != mesh.source_local_submesh_index
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
    std::vector<NativePbdSidecarHint> pbd_hints;
    int material_wrapper_count = 0;
};

static std::uint64_t g_sidecar_parse_cache_hits = 0;
static std::uint64_t g_sidecar_parse_cache_misses = 0;

static std::uint64_t sidecar_parse_cache_hits() {
    return g_sidecar_parse_cache_hits;
}

static std::uint64_t sidecar_parse_cache_misses() {
    return g_sidecar_parse_cache_misses;
}

static std::map<std::string, ParsedMaterialSidecar>& resident_parsed_material_sidecar_cache() {
    static std::map<std::string, ParsedMaterialSidecar> cache;
    return cache;
}

static size_t resident_parsed_material_sidecar_cache_count() {
    return resident_parsed_material_sidecar_cache().size();
}

static void release_resident_parsed_material_sidecar_cache() {
    std::map<std::string, ParsedMaterialSidecar> empty;
    resident_parsed_material_sidecar_cache().swap(empty);
}

// Parsed sidecars are small (extracted refs and hints, not the XML), but a
// long session can accumulate one per model. Keep them resident so repeat
// previews skip the decode+parse, and clear only past a generous bound.
static constexpr size_t kResidentParsedMaterialSidecarMaxCount = 4096;

static void trim_resident_parsed_material_sidecar_cache() {
    if (resident_parsed_material_sidecar_cache().size() > kResidentParsedMaterialSidecarMaxCount) {
        release_resident_parsed_material_sidecar_cache();
    }
}

static const ParsedMaterialSidecar& cached_parsed_material_sidecar(const ArchiveEntryRef& sidecar) {
    auto& cache = resident_parsed_material_sidecar_cache();
    const std::string key = archive_ref_identity(sidecar);
    auto found = cache.find(key);
    if (found != cache.end()) {
        ++g_sidecar_parse_cache_hits;
        return found->second;
    }
    ++g_sidecar_parse_cache_misses;
    std::vector<char> sidecar_bytes = read_archive_ref_decoded_bytes(sidecar);
    std::string sidecar_text(sidecar_bytes.begin(), sidecar_bytes.end());
    ParsedMaterialSidecar parsed;
    parsed.shader_family = extract_shader_family_hint(sidecar_text);
    if (parsed.shader_family.empty()) {
        parsed.shader_family = sidecar.extension == ".pami" ? "StaticMaterial" : "";
    }
    parsed.shader_rule = shader_rule_for_family(parsed.shader_family);
    parsed.parameter_summary = summarize_sidecar_parameters(sidecar_text);
    parsed.pbd_hints = extract_native_pbd_sidecar_hints(sidecar_text, sidecar.path);
    parsed.refs = extract_sidecar_texture_refs(sidecar_text);
    parsed.material_wrapper_count = 0;
    for (const SidecarTextureRef& ref : parsed.refs) {
        if (ref.material_wrapper_index >= 0) {
            parsed.material_wrapper_count = std::max(parsed.material_wrapper_count, ref.material_wrapper_index + 1);
        }
    }
    if (parsed.refs.empty()) {
        const std::vector<MaterialParameterRecord> material_parameters = extract_material_parameters(sidecar_text);
        for (const std::string& token : extract_dds_tokens(sidecar_text)) {
            parsed.refs.push_back(SidecarTextureRef{token, "", "", parsed.shader_family, -1, material_parameters});
        }
    }
    return cache.emplace(key, std::move(parsed)).first->second;
}

static const NativePbdSidecarHint* best_native_pbd_hint_for_binding(
    const std::vector<NativePbdSidecarHint>& hints,
    const std::string& binding_material_name,
    const std::string& texture_ref_material_name,
    const std::string& texture_parameter_name
) {
    const NativePbdSidecarHint* best = nullptr;
    int best_score = 0;
    const std::string material_key = normalized_material_key(binding_material_name);
    const std::string ref_material_key = normalized_material_key(texture_ref_material_name);
    const std::string parameter_key = normalized_key(texture_parameter_name);
    const std::string binding_context = binding_material_name + " " + texture_ref_material_name + " " + texture_parameter_name;
    const bool binding_looks_like_soft_physics = native_soft_pbd_token_match(binding_context);
    if (native_rigid_pbd_token_match(binding_context) && !binding_looks_like_soft_physics) {
        return nullptr;
    }
    const bool binding_looks_like_cloth = native_cloth_token_match(
        binding_material_name + " " + texture_ref_material_name + " " + texture_parameter_name
    );
    for (const NativePbdSidecarHint& hint : hints) {
        if (hint.simulation_material_name.empty()) continue;
        if (!native_pbd_hint_is_soft_physics(hint)) continue;
        int score = 0;
        const std::string hint_material_key = normalized_material_key(hint.material_name);
        const std::string hint_submesh_key = normalized_material_key(hint.submesh_name);
        const std::string hint_pbd_key = normalized_material_key(hint.simulation_material_name);
        if (!hint_material_key.empty() && (hint_material_key == material_key || hint_material_key == ref_material_key)) score += 100;
        if (!hint_submesh_key.empty() && (hint_submesh_key == material_key || hint_submesh_key == ref_material_key)) score += 90;
        if (!hint_pbd_key.empty() && (material_key.find(hint_pbd_key) != std::string::npos || ref_material_key.find(hint_pbd_key) != std::string::npos)) score += 40;
        if (binding_looks_like_soft_physics) score += 20;
        if (binding_looks_like_cloth) score += 20;
        if (!parameter_key.empty() && native_soft_pbd_token_match(parameter_key)) score += 20;
        if (score > best_score) {
            best_score = score;
            best = &hint;
        }
    }
    return best_score >= 80 ? best : nullptr;
}

// Crimson's `_sp` maps carry their surface response in G and B, read out of the
// shipped shaders rather than inferred from the filename suffix:
//
//   Standard/Cloth/Fur/Emissive/...  sample G and B only. G is roughness,
//                                    B is metalness. R and A are never sampled.
//   Skin/SkinWrinkle/EyeCover        sample R, G and B. R is the subsurface
//                                    term, which the preview has no lobe for,
//                                    so it is dropped rather than folded into
//                                    occlusion. G is roughness, B is metalness.
//   Hair/AnimalHair/WhiteHornHair    sample G alone; hair carries no metal.
//
// R is *not* occlusion in any family. It is the most spatially detailed channel,
// which is why it reads like a baked AO map, but only the skin shaders sample it
// and they use it as subsurface. `_sp` files are BC1, so alpha is synthesised
// opaque and never carries data; nothing may read it.
static std::string material_response_channel_layout(const std::string& shader_rule) {
    if (shader_rule == "hair") return "g=roughness";
    // Skin packs its `_sp` differently and blue is not metal there. On equipment
    // the red channel is a constant 1.0 filler and blue is metalness, varying by
    // material -- cd_phm_03_handle_0004_sp measures B 0.005 and
    // cd_phm_03_shield_0090_sp measures 0.877. A skin map does neither:
    // cd_phm_00_head_0001_sp measures R 0.770, the subsurface term the skin
    // shaders sample, and B 0.997 flat across the whole face.
    //
    // Read as metalness that says a face is 100% metal, which is what it did:
    // 24 of 72 sampled heads classified metal rather than skin, and a metal
    // classification takes the lower ambient floor and the cut diffuse, so the
    // face rendered at 0.45 of the brightness its own albedo carries. Declaring
    // only what the channel actually holds keeps the classifier, and the
    // renderer, from reading a number that is not there.
    if (shader_rule == "skin") return "g=roughness";
    return "g=roughness,b=metalness";
}

static std::string packed_channels_for_role(
    const std::string& role,
    const std::string& name,
    const std::string& parameter_name,
    const std::string& shader_rule
) {
    const std::string lower = lower_copy(name + " " + parameter_name);
    const std::string parameter_key = normalized_key(parameter_name);
    if (role == "material") {
        if (lower.find("orm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (lower.find("rma") != std::string::npos) return "r=roughness,g=metalness,b=occlusion";
        if (lower.find("mra") != std::string::npos) return "r=metalness,g=roughness,b=occlusion";
        if (lower.find("arm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (parameter_key == "colorblendingmasktexture" && lower.find("_ma") != std::string::npos) {
            // A colour-blending mask selects which authored colour layer owns a
            // texel. Declaring it as packed occlusion/roughness/metal made the
            // consumer read a layer weight as a surface property, which is how
            // dyed cloth and leather picked up a metal response they never had.
            return "layer:color_blending_mask";
        }
        if (parameter_key == "detailmasktexture" || lower.find("_mg") != std::string::npos) {
            return "layer:detail_grime_dye_mask";
        }
        if (
            lower.find("_sp") != std::string::npos
            || parameter_key.find("grimematerialtexture") != std::string::npos
            || parameter_key.find("detailmaterialmask") != std::string::npos
            || parameter_key == "materialtexture"
        ) {
            // Keep the layer marker for consumers that decode the map themselves,
            // and declare the component layout so a consumer that samples the DDS
            // directly binds roughness and metal to the channels the game reads.
            return "layer:material_response," + material_response_channel_layout(shader_rule);
        }
        if (lower.find("_ma") != std::string::npos) return "diagnostic:crimson_material_mask";
        if (lower.find("_m") != std::string::npos) return "diagnostic:packed_material_mask";
    }
    if (role == "detail") return "layer:detail_grime_dye_mask";
    if (role == "specular") {
        // Only Crimson's `_sp` maps carry the G/B surface layout. A gloss or
        // smoothness map that also lands in this slot is a different contract,
        // so it keeps the bare marker and no component claim.
        if (lower.find("_sp") != std::string::npos) {
            return "layer:material_response," + material_response_channel_layout(shader_rule);
        }
        return "layer:material_response";
    }
    if (role == "height") return "height";
    if (role == "normal") return "normal_xy";
    if (role == "opacity") {
        // R, G and B are three alternative tear shapes and the game picks one per
        // character. A preview has no such choice, so it shows the first, which is
        // the primary channel everywhere else in this format. Alpha is a broad
        // unrelated field covering 42% of the sheet and is not coverage.
        return lower.find("_m") != std::string::npos ? "r=opacity" : "";
    }
    return "";
}

static std::string layer_channel_from_parameter(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    if (key.find("detailmasktexture") != std::string::npos) return "b";
    if (key.ends_with("r")) return "r";
    if (key.ends_with("g")) return "g";
    if (key.ends_with("b")) return "b";
    if (key.ends_with("a")) return "a";
    if (key.find("grime") != std::string::npos) return "r";
    return "r";
}

// Whether the parameter itself names the mask channel that selects its layer.
// `_detailDiffuseMaskR/G/B` do; `_detailMaskTexture` is the mask, not a layer,
// and its "b" above is a fallback for layers that name no channel of their own.
static bool layer_parameter_names_channel(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    if (key.find("detailmasktexture") != std::string::npos) return false;
    return key.ends_with("r") || key.ends_with("g") || key.ends_with("b") || key.ends_with("a");
}

static int layer_channel_index(const std::string& channel) {
    const std::string value = lower_copy(channel);
    if (value == "g") return 1;
    if (value == "b") return 2;
    if (value == "a") return 3;
    return 0;
}

static std::string layer_role_from_parameter(const std::string& parameter_name, const std::string& role) {
    const std::string key = normalized_key(parameter_name);
    // Coverage is never a colour layer. The tear shell's mask arrives on
    // `_baseColorTexture`, whose name matches the "colortexture" layer rule
    // below, and a consumer that filters layer-only roles then discarded the
    // one input that says which part of the shell is a tear.
    if (role == "opacity") return "opacity";
    if (key.find("grime") != std::string::npos) return "grime";
    if (key.find("detail") != std::string::npos || key.find("dyeing") != std::string::npos) return "detail";
    if (key.find("damage") != std::string::npos) return "damage";
    if (key.find("overlay") != std::string::npos) return "overlay";
    if (key.find("layer") != std::string::npos || key.find("colortexture") != std::string::npos) return "layer";
    if (role == "base") return "base";
    if (role == "detail") return "detail_mask";
    if (role == "material") return "material_response";
    if (role == "specular") return "specular_response";
    return role.empty() ? "material" : role;
}

static float layer_weight_from_parameters(
    const std::vector<MaterialParameterRecord>& parameters,
    const std::string& layer_role,
    const std::string& channel
) {
    const int channel_index = layer_channel_index(channel);
    if (layer_role == "base") return 1.0f;
    if (layer_role == "overlay") return 0.24f;
    if (layer_role == "grime") {
        const auto opacity = byte4_parameter_channels(parameters, {"grimeBlendingOpacityParameter", "grimeOpacity"});
        float value = opacity[std::min(channel_index, 3)];
        if (value <= 0.01f) value = 0.34f;
        return std::clamp(value, 0.03f, 0.72f);
    }
    if (layer_role == "detail") {
        const auto global = byte4_parameter_channels(parameters, {"dyeingGlobalOpacity"});
        float value = global[std::min(channel_index, 3)];
        if (value <= 0.01f) value = 0.42f;
        const auto property = byte4_parameter_channels(parameters, {"dyeingPropertyBlend"});
        value *= std::max(0.25f, std::max({property[0], property[1], property[2], value}));
        return std::clamp(value, 0.04f, 0.68f);
    }
    if (layer_role == "damage") {
        const auto damage = byte4_parameter_channels(parameters, {"damageBlendingParameter"});
        float value = std::max({damage[0], damage[1], damage[2], damage[3], 0.18f});
        return std::clamp(value, 0.04f, 0.58f);
    }
    return 0.28f;
}

static std::array<float, 4> tint_for_layer(
    const std::vector<MaterialParameterRecord>& parameters,
    const std::string& layer_role,
    const std::string& channel
) {
    std::vector<std::string> candidates;
    if (layer_role == "grime") {
        // _tintColor{R,G,B} is the base tint of the three layers the
        // _colorBlendingMaskTexture selects; it sits alongside
        // _grimeDiffuseTexture{R,G,B} one-for-one in the PAC.
        // _scratchTintColor{R,G,B} is the wear accent for the same channels and
        // carries a low alpha strength, so it is an overlay rather than the
        // surface colour. Preferring scratch here painted the blade of
        // cd_phm_02_sword_0014 near-white (#dbdbdb) and its grip yellow
        // (#dbc03e) instead of the authored #ae8c54 gold and #625142 brown.
        candidates = {"tintColor" + channel, "dyeingDetailLayerColorMask" + channel, "scratchTintColor" + channel};
    } else if (layer_role == "detail") {
        candidates = {"dyeingDetailLayerColorMask" + channel, "dyeingColorMask" + channel, "tintColor" + channel};
    } else if (layer_role == "overlay") {
        candidates = {"overlayColor", "tintColor" + channel, "tintColor"};
    } else {
        candidates = {
            "tintColor" + channel,
            "dyeingColorMask" + channel,
            "baseColor" + channel,
            "diffuseColor" + channel,
            "albedoColor" + channel,
            "materialColor" + channel,
            "baseColor",
            "diffuseColor",
            "albedoColor",
            "materialColor",
            "tintColor"
        };
    }
    for (const std::string& candidate : candidates) {
        const MaterialParameterRecord* parameter = find_material_parameter(parameters, {candidate.c_str()});
        if (parameter != nullptr && parameter->kind == "color") {
            return color_parameter_value(parameter->value);
        }
    }
    return {1.0f, 1.0f, 1.0f, 1.0f};
}

static std::string evidence_grade_for_binding(
    const TextureBinding& binding,
    const TechniqueParameterInfo* technique_parameter
) {
    if (binding.material_output_quality == "exact" && technique_parameter != nullptr && technique_parameter->declared) {
        return "corpus_inferred";
    }
    if (binding.material_output_quality == "exact") return "corpus_inferred";
    if (binding.material_output_quality == "inferred") return "approximate";
    return "approximate";
}

static std::string role_from_parameter_shader_and_name(
    const std::string& parameter_name,
    const std::string& shader_rule,
    const std::string& texture_name,
    const TechniqueParameterInfo* technique_parameter = nullptr
) {
    const std::string p = lower_copy(parameter_name);
    const std::string t = lower_copy(texture_name);
    if (p.find("emissive") != std::string::npos || p.find("glow") != std::string::npos || p.find("illum") != std::string::npos || t.find("_emi.dds") != std::string::npos || t.find("emissive") != std::string::npos) return "emissive";
    if (p.find("flow") != std::string::npos) return "flow";
    if (shader_rule == "hair" && (p == "_flowtexture" || p.find("flowtexture") != std::string::npos || t.find("_f.dds") != std::string::npos)) return "flow";
    if (p.find("ssdm") != std::string::npos || p.find("direction") != std::string::npos || t.find("_dr.dds") != std::string::npos) return "flow";
    if ((p.find("alpha") != std::string::npos || p.find("opacity") != std::string::npos) && p.find("base") == std::string::npos) return "opacity";
    // The tear shell's `_m` atlas arrives on a colour parameter, and the technique
    // declares that parameter, so this has to precede the declared-parameter block
    // below. Its three colour channels are tear-shape coverage, not albedo:
    // routing it to opacity clips the shell to the tear itself, where leaving it
    // rejected as a technical base drew the whole card as a grey sheet.
    if (shader_rule == "tear"
        && t.find("_m.dds") != std::string::npos
        && (p.find("basecolor") != std::string::npos
            || p.find("diffuse") != std::string::npos
            || p.find("albedo") != std::string::npos)) {
        return "opacity";
    }
    // `_tornPatternTexture` is the shape of a tear, not a surface input. It has
    // no colour role, no normal, no response -- it selects where a garment is
    // torn. Left to fall through it landed in the base role, and on
    // cd_m0001_00_so_pgm_ub_belt_42008 the shared library pattern it points at
    // became the albedo, rendering the garment as neon green and magenta
    // stripes. Naming its own role keeps the binding on record as evidence
    // while leaving it out of every channel the renderer samples.
    if (p.find("tornpattern") != std::string::npos || t.find("_tp.dds") != std::string::npos) {
        return "torn_pattern";
    }
    if (technique_parameter != nullptr && technique_parameter->declared) {
        const std::string declared_type = lower_copy(technique_parameter->type);
        const std::string declared_default = lower_copy(technique_parameter->default_value);
        const bool declared_texture = declared_type.find("texture") != std::string::npos || p.find("texture") != std::string::npos;
        if (declared_texture) {
            if (p.find("emissive") != std::string::npos || p.find("glow") != std::string::npos || p.find("illum") != std::string::npos) return "emissive";
            if (p.find("flow") != std::string::npos) return "flow";
            if (p.find("ssdm") != std::string::npos || p.find("direction") != std::string::npos) return "flow";
            if (p.find("normal") != std::string::npos || declared_default.find("0xff7f7f00") != std::string::npos) return "normal";
            if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos) return "height";
            if (p.find("specular") != std::string::npos || p.find("gloss") != std::string::npos || p.find("smoothness") != std::string::npos) return "specular";
            if (p.find("roughness") != std::string::npos) return "roughness";
            if (p.find("metallic") != std::string::npos || p.find("metalness") != std::string::npos) return "metalness";
            if (p.find("occlusion") != std::string::npos || p.find("ambientocclusion") != std::string::npos) return "occlusion";
            if ((p.find("diffuse") != std::string::npos || p.find("basecolor") != std::string::npos || p.find("albedo") != std::string::npos) && p.find("mask") == std::string::npos) return "base";
            if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
            if (p.find("overlaycolor") != std::string::npos || p.find("layerbasecolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
            if (p.find("mask") != std::string::npos && (p.find("detail") != std::string::npos || p.find("blend") != std::string::npos || p.find("layer") != std::string::npos)) return "detail";
            if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p == "_masktexture") return "material";
        }
    }
    if (p.find("normal") != std::string::npos || p == "n" || t.find("_n.dds") != std::string::npos) return "normal";
    if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos || t.find("_disp.dds") != std::string::npos) return "height";
    if (p.find("roughness") != std::string::npos || t.find("roughness") != std::string::npos) return "roughness";
    if (p.find("metallic") != std::string::npos || p.find("metalness") != std::string::npos || t.find("metallic") != std::string::npos || t.find("metalness") != std::string::npos) return "metalness";
    if (p.find("occlusion") != std::string::npos || p.find("ambientocclusion") != std::string::npos || t.find("_ao.dds") != std::string::npos) return "occlusion";
    // The authored parameter outranks the file suffix: SkinnedMeshStandard writes its
    // packed roughness/metal map to _materialTexture and still names the file _sp.dds,
    // so matching the suffix first strands it in the specular slot and drops the batch
    // onto the legacy specular-gloss response. Skin keeps the suffix reading below.
    const bool parameter_declares_material_map =
        p.find("material") != std::string::npos && shader_rule != "skin";
    if (
        p.find("specular") != std::string::npos
        || p.find("_sp") != std::string::npos
        || (t.find("_sp.dds") != std::string::npos && !parameter_declares_material_map)
    ) return "specular";
    if (p.find("gloss") != std::string::npos || p.find("smoothness") != std::string::npos || t.find("gloss") != std::string::npos || t.find("smoothness") != std::string::npos) return "specular";
    if ((p.find("diffuse") != std::string::npos || p.find("basecolor") != std::string::npos || p.find("albedo") != std::string::npos) && p.find("mask") == std::string::npos) return "base";
    if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p.find("blending") != std::string::npos || t.find("_ma.dds") != std::string::npos || t.find("_m.dds") != std::string::npos) return "material";
    if (p.find("detail") != std::string::npos || p.find("grime") != std::string::npos || p.find("dye") != std::string::npos || p.find("mask") != std::string::npos || t.find("_mg.dds") != std::string::npos) {
        if (p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos || p.find("color") != std::string::npos) return "base";
        return "detail";
    }
    if (p.find("overlaycolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
    if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
    if (shader_rule == "skin" && t.find("_sp.dds") != std::string::npos) return "specular";
    return texture_role_from_name(texture_name);
}

static std::string semantic_type_for_role(const std::string& role) {
    if (role == "base") return "albedo";
    if (role == "emissive") return "emissive";
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "roughness") return "roughness";
    if (role == "metalness") return "metalness";
    if (role == "occlusion") return "ao";
    if (role == "detail") return "detail_mask";
    if (role == "flow") return "flow";
    if (role == "opacity") return "opacity";
    return "packed_material";
}
