static std::string extracted_dds_path_for_entry(
    const ArchiveEntryRef& ref,
    const fs::path& cache_root,
    std::vector<std::string>& notes
) {
    if (ref.path.empty() || ref.extension != ".dds") return "";
    if (ref.compressed() && ref.comp_size != ref.orig_size) {
        // Partial DDS entries are reconstructed with PATHC before reaching this cache.
        // The cache key includes the native extraction version to avoid stale padded DDS.
    }
    const std::string identity =
        "native_dds_v" + std::to_string(kNativeDdsExtractionVersion) + "|"
        + ref.pamt_path.string() + "|" + ref.path + "|" + std::to_string(ref.offset) + "|"
        + std::to_string(ref.comp_size) + "|" + std::to_string(ref.orig_size);
    const fs::path out_path = cache_root / "dds" / (hex64(fnv1a64(identity)) + "_" + safe_filename(ref.basename));
    const std::uint64_t expected_size = ref.orig_size > 0 ? ref.orig_size : ref.comp_size;
    if (expected_size > 0) {
        try {
            if (fs::is_regular_file(out_path) && fs::file_size(out_path) == expected_size) {
                std::ifstream cached(out_path, std::ios::binary);
                char magic[4] = {};
                cached.read(magic, sizeof(magic));
                if (cached.gcount() == 4 && std::string(magic, magic + 4) == "DDS ") {
                    return fs::absolute(out_path).string();
                }
            }
        } catch (...) {
        }
    }
    std::vector<char> data;
    try {
        data = read_archive_ref_decoded_bytes(ref);
    } catch (const std::exception& exc) {
        notes.push_back("DDS read failed:" + ref.basename + ":" + exc.what());
        return "";
    }
    if (data.size() < 4 || std::string(data.data(), data.data() + 4) != "DDS ") {
        notes.push_back("DDS candidate skipped:missing header:" + ref.basename);
        return "";
    }
    if (ref.orig_size > data.size() && data.size() >= 128) {
        data.resize(static_cast<size_t>(ref.orig_size), 0);
        notes.push_back("DDS sparse padded:" + ref.basename);
    }
    try {
        if (!fs::is_regular_file(out_path) || fs::file_size(out_path) != data.size()) {
            write_binary(out_path, data);
        }
    } catch (const std::exception& exc) {
        notes.push_back("DDS cache write failed:" + ref.basename + ":" + exc.what());
        return "";
    }
    return fs::absolute(out_path).string();
}

struct DdsHeaderInfo {
    int width = 0;
    int height = 0;
    std::string format;
};

static std::uint32_t read_u32_le_raw(const std::vector<char>& data, size_t offset) {
    if (offset + 4 > data.size()) return 0;
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint32_t>(p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24));
}

static DdsHeaderInfo inspect_dds_header_file(const std::string& path) {
    static std::map<std::string, DdsHeaderInfo> cache;
    auto cached = cache.find(path);
    if (cached != cache.end()) return cached->second;
    DdsHeaderInfo info;
    std::ifstream in(fs::path(path), std::ios::binary);
    if (!in) return info;
    std::vector<char> header(148, 0);
    in.read(header.data(), static_cast<std::streamsize>(header.size()));
    const size_t count = static_cast<size_t>(std::max<std::streamsize>(0, in.gcount()));
    header.resize(count);
    if (header.size() < 128 || std::string(header.data(), header.data() + 4) != "DDS ") return info;
    info.height = static_cast<int>(read_u32_le_raw(header, 12));
    info.width = static_cast<int>(read_u32_le_raw(header, 16));
    if (header.size() >= 88) {
        std::string fourcc(header.data() + 84, header.data() + 88);
        if (fourcc == "DX10" && header.size() >= 132) {
            info.format = "DXGI_" + std::to_string(read_u32_le_raw(header, 128));
        } else {
            info.format = fourcc;
        }
    }
    if (!path.empty() && cache.size() < 4096) {
        cache.emplace(path, info);
    }
    return info;
}

static bool dds_format_is_data_only_for_visible_base(const std::string& raw_format) {
    const std::string format = lower_copy(raw_format);
    if (format.empty()) return false;
    if (format == "bc4u" || format == "bc4s" || format == "ati1") return true;
    if (format == "bc5u" || format == "bc5s" || format == "ati2" || format == "rxgb") return true;
    if (format == "dxgi_80" || format == "dxgi_81" || format == "dxgi_83" || format == "dxgi_84") return true;
    if (format.find("bc4") != std::string::npos || format.find("bc5") != std::string::npos) return true;
    return false;
}

static int material_match_score(const TextureBinding& binding, const NativeSubmesh& mesh, const std::string& desired_role) {
    int score = 0;
    if (binding.role == desired_role) score += 100;
    if (desired_role == "material" && (binding.role == "detail" || binding.role == "specular")) score += 16;
    if (desired_role == "base" && role_is_technical_for_base(binding.role)) score -= 200;
    if (desired_role == "base" && dds_format_is_data_only_for_visible_base(binding.dds_format)) score -= 240;
    if (desired_role == "base") {
        const int largest_dimension = std::max(binding.dds_width, binding.dds_height);
        if (largest_dimension >= 2048) score += 24;
        else if (largest_dimension >= 1024) score += 18;
        else if (largest_dimension >= 512) score += 8;
        else if (largest_dimension > 0) score -= 42;
    }
    const std::string material = lower_copy(mesh.material + " " + mesh.name);
    const std::string texture = lower_copy(
        binding.texture_name + " " +
        binding.archive_path + " " +
        binding.material_name + " " +
        binding.parameter_name
    );
    std::vector<std::string> material_tokens;
    std::string current;
    for (char ch : material) {
        if (std::isalnum(static_cast<unsigned char>(ch))) current.push_back(ch);
        else if (!current.empty()) {
            material_tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) material_tokens.push_back(current);
    for (const std::string& token : material_tokens) {
        if (token.size() >= 3 && texture.find(token) != std::string::npos) score += 12;
    }
    const std::string binding_material = lower_copy(binding.material_name);
    if (!binding_material.empty() && material.find(binding_material) != std::string::npos) score += 70;
    if (!binding_material.empty() && texture.find(material) != std::string::npos) score += 20;
    if (texture.find(material) != std::string::npos && !material.empty()) score += 40;
    return score;
}

static std::string normalized_material_key(const std::string& text) {
    std::string key = lower_copy(basename_from_path(text));
    if (key.ends_with(".dds")) key = key.substr(0, key.size() - 4);
    return key;
}

static std::string normalized_texture_family_key(const std::string& text) {
    std::string key = normalized_material_key(text);
    for (const std::string& suffix : {"_disp", "_ma", "_mg", "_sp", "_m", "_n", "_o", "_dr"}) {
        if (key.size() > suffix.size() && key.ends_with(suffix)) {
            key.resize(key.size() - suffix.size());
            break;
        }
    }
    return key;
}

static bool material_keys_overlap(const std::string& a, const std::string& b) {
    if (a.empty() || b.empty()) return false;
    return a == b || a.find(b) != std::string::npos || b.find(a) != std::string::npos;
}

static std::vector<std::string> material_key_tokens(const std::string& key) {
    std::vector<std::string> tokens;
    std::string current;
    for (char ch : lower_copy(key)) {
        if (std::isalnum(static_cast<unsigned char>(ch))) current.push_back(ch);
        else if (!current.empty()) {
            tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) tokens.push_back(current);
    return tokens;
}

static bool material_key_has_token(const std::string& key, const std::string& token) {
    const std::vector<std::string> tokens = material_key_tokens(key);
    return std::find(tokens.begin(), tokens.end(), token) != tokens.end();
}

static std::vector<std::string> material_identity_tokens(const std::string& key) {
    std::vector<std::string> result;
    for (const std::string& token : material_key_tokens(key)) {
        if (token == "cd" || token == "00" || token == "01" || token == "02" || token == "03") continue;
        if (token.size() < 3) continue;
        result.push_back(token);
    }
    return result;
}

static int material_key_token_cover_score(const std::string& texture_family_key, const std::string& mesh_key) {
    const std::vector<std::string> mesh_tokens = material_identity_tokens(mesh_key);
    if (texture_family_key.empty() || mesh_tokens.empty()) return 0;
    int matched = 0;
    for (const std::string& token : mesh_tokens) {
        if (material_key_has_token(texture_family_key, token)) ++matched;
    }
    if (matched == static_cast<int>(mesh_tokens.size())) {
        return 118 + matched * 12;
    }
    if (matched >= 2) {
        return matched * 34;
    }
    return 0;
}

static const std::vector<std::string>& material_identity_specific_part_tokens() {
    static const std::vector<std::string> tokens = {
        "hand", "head", "foot", "eye", "eyecover", "hair", "beard", "fur", "arm", "leg", "lb", "ub",
        "uw", "underwear", "nude",
        "hel", "helmet", "mask", "chain", "blade", "guard", "handle", "acc", "belt", "cloak", "flag", "cloth", "fabric", "sho"
    };
    return tokens;
}

static bool material_identity_has_conflicting_specific_part(
    const std::string& texture_family_key,
    const std::string& mesh_key_a,
    const std::string& mesh_key_b
) {
    if (texture_family_key.empty()) return false;
    for (const std::string& token : material_identity_specific_part_tokens()) {
        if (!material_key_has_token(texture_family_key, token)) continue;
        if (material_key_has_token(mesh_key_a, token) || material_key_has_token(mesh_key_b, token)) continue;
        return true;
    }
    return false;
}

static int material_identity_extra_part_penalty(const std::string& texture_family_key, const std::string& mesh_key_a, const std::string& mesh_key_b) {
    if (texture_family_key.empty()) return 0;
    int penalty = 0;
    for (const std::string& token : material_identity_specific_part_tokens()) {
        if (!material_key_has_token(texture_family_key, token)) continue;
        if (material_key_has_token(mesh_key_a, token) || material_key_has_token(mesh_key_b, token)) continue;
        penalty += 96;
    }
    return penalty;
}

static bool model_family_fallback_allowed_for_sidecar_ref(
    const std::string& ref_material_key,
    const std::string& texture_family_key,
    const std::string& model_family_key
) {
    if (ref_material_key.empty() || model_family_key.empty()) return false;
    if (!material_keys_overlap(ref_material_key, model_family_key)) return false;
    if (ref_material_key == model_family_key) return true;
    if (material_identity_has_conflicting_specific_part(ref_material_key, model_family_key, "")) return false;
    if (material_identity_has_conflicting_specific_part(texture_family_key, model_family_key, "")) return false;
    return material_identity_extra_part_penalty(ref_material_key, model_family_key, "") == 0
        && material_identity_extra_part_penalty(texture_family_key, model_family_key, "") == 0;
}

static bool material_keys_match_for_identity(const std::string& candidate_key, const std::string& mesh_key) {
    if (material_keys_overlap(candidate_key, mesh_key)) return true;
    const int cover_score = material_key_token_cover_score(candidate_key, mesh_key)
        - material_identity_extra_part_penalty(candidate_key, mesh_key, "");
    return cover_score >= 100;
}

static std::string material_component_key_from_path(const std::string& path) {
    std::string key = normalized_material_key(stem_from_path(path));
    bool stripped = true;
    while (stripped) {
        stripped = false;
        for (const std::string& suffix : {"_sub01", "_sub02", "_sub03", "_sub1", "_sub2", "_sub3", "_dm01", "_dm02", "_dm", "_op", "_v", "_s"}) {
            if (key.size() > suffix.size() && key.ends_with(suffix)) {
                key.resize(key.size() - suffix.size());
                stripped = true;
                break;
            }
        }
    }
    return key;
}

static bool material_sidecar_matches_mesh_source(const TextureBinding& binding, const NativeSubmesh& mesh) {
    if (binding.sidecar_path.empty() || mesh.source_model_path.empty()) return true;
    const std::string sidecar_key = material_component_key_from_path(binding.sidecar_path);
    const std::string mesh_source_key = material_component_key_from_path(mesh.source_model_path);
    if (sidecar_key.empty() || mesh_source_key.empty()) return true;
    return sidecar_key == mesh_source_key || material_keys_overlap(sidecar_key, mesh_source_key);
}

static bool material_binding_matches_mesh_source(const TextureBinding& binding, const NativeSubmesh& mesh) {
    if (!material_sidecar_matches_mesh_source(binding, mesh)) return false;
    if (binding.source_authority != "embedded_mesh" || binding.linked_mesh_path.empty() || mesh.source_model_path.empty()) {
        return true;
    }
    const std::string binding_key = material_component_key_from_path(binding.linked_mesh_path);
    const std::string mesh_source_key = material_component_key_from_path(mesh.source_model_path);
    if (binding_key.empty() || mesh_source_key.empty()) return true;
    return binding_key == mesh_source_key || material_keys_overlap(binding_key, mesh_source_key);
}

static int material_identity_text_match_score(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string mesh_text = lower_copy(mesh.material + " " + mesh.name);
    const std::string binding_text = lower_copy(binding.material_name + " " + binding.texture_name + " " + binding.archive_path);
    const std::string mesh_key_a = normalized_material_key(mesh.material);
    const std::string mesh_key_b = normalized_material_key(mesh.name);
    const std::string binding_key = normalized_material_key(binding.material_name);
    const std::string texture_family_key = normalized_texture_family_key(binding.texture_name.empty() ? binding.archive_path : binding.texture_name);
    int score = 0;
    if (!binding_key.empty() && (!mesh_key_a.empty() || !mesh_key_b.empty())) {
        if (binding_key == mesh_key_a || binding_key == mesh_key_b) score += 160;
        if (material_keys_overlap(binding_key, mesh_key_a)) score += 72;
        if (material_keys_overlap(binding_key, mesh_key_b)) score += 72;
        if (material_keys_overlap(texture_family_key, mesh_key_a)) score += 132;
        if (material_keys_overlap(texture_family_key, mesh_key_b)) score += 132;
        if (score == 0) {
            const int token_bridge_score =
                material_key_token_cover_score(binding_key, mesh_key_a)
                + material_key_token_cover_score(binding_key, mesh_key_b)
                + material_key_token_cover_score(texture_family_key, mesh_key_a)
                + material_key_token_cover_score(texture_family_key, mesh_key_b);
            if (token_bridge_score < 100) return 0;
            score += token_bridge_score;
        }
    }
    if (!texture_family_key.empty()) {
        if (material_keys_overlap(texture_family_key, mesh_key_a)) score += 80;
        if (material_keys_overlap(texture_family_key, mesh_key_b)) score += 80;
        score += material_key_token_cover_score(texture_family_key, mesh_key_a);
        score += material_key_token_cover_score(texture_family_key, mesh_key_b);
    }
    std::string current;
    std::vector<std::string> mesh_tokens;
    for (char ch : mesh_text) {
        if (std::isalnum(static_cast<unsigned char>(ch))) current.push_back(ch);
        else if (!current.empty()) {
            mesh_tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) mesh_tokens.push_back(current);
    for (const std::string& token : mesh_tokens) {
        if (token.size() >= 4 && binding_text.find(token) != std::string::npos) score += 14;
    }
    score -= material_identity_extra_part_penalty(texture_family_key, mesh_key_a, mesh_key_b);
    return score;
}

static int material_identity_match_score(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const int text_score = material_identity_text_match_score(binding, mesh);
    if (binding.material_wrapper_order_authoritative && binding.material_wrapper_index >= 0 && mesh.source_local_submesh_index >= 0) {
        if (!material_binding_matches_mesh_source(binding, mesh)) return 0;
        if (binding.material_wrapper_index == mesh.source_local_submesh_index) {
            return 220 + std::min(std::max(text_score, 0), 180);
        }
        const std::string mesh_submesh_key = normalized_material_key(mesh.name);
        const std::string binding_key = normalized_material_key(binding.material_name);
        const std::string texture_family_key = normalized_texture_family_key(binding.texture_name.empty() ? binding.archive_path : binding.texture_name);
        const bool submesh_specific_match =
            material_keys_overlap(binding_key, mesh_submesh_key)
            || material_keys_overlap(texture_family_key, mesh_submesh_key);
        return submesh_specific_match && text_score >= 120 ? std::min(text_score, 220) : 0;
    }
    return text_score;
}

static bool material_wrapper_matches_mesh_local_index(const TextureBinding& binding, const NativeSubmesh& mesh) {
    return binding.material_wrapper_order_authoritative
        && binding.material_wrapper_index >= 0
        && mesh.source_local_submesh_index >= 0
        && binding.material_wrapper_index == mesh.source_local_submesh_index
        && material_binding_matches_mesh_source(binding, mesh);
}

static bool material_identity_requires_exact_path_match(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string binding_material = lower_copy(binding.material_name);
    const std::string mesh_material = lower_copy(mesh.material + " " + mesh.name);
    return binding_material.find(".dds") != std::string::npos && mesh_material.find(".dds") != std::string::npos;
}

static bool authoritative_wrapper_visible_base_for_mesh(const TextureBinding& binding, const NativeSubmesh& mesh) {
    if (binding.role != "base") return false;
    if (binding.source_authority != "exact_sidecar") return false;
    if (!binding.material_wrapper_order_authoritative) return false;
    if (!parameter_is_authoritative_visible_base(binding.parameter_name)) return false;
    if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)) return false;
    if (placeholder_visible_base_path(binding.archive_path) || placeholder_visible_base_path(binding.texture_name)) return false;
    if (base_binding_is_low_authority_overlay(&binding)) return false;
    return material_wrapper_matches_mesh_local_index(binding, mesh) || material_identity_match_score(binding, mesh) >= 300;
}

static bool support_role_requires_material_scope(const std::string& desired_role) {
    return desired_role == "normal"
        || desired_role == "material"
        || desired_role == "height"
        || desired_role == "specular"
        || desired_role == "detail"
        || desired_role == "emissive";
}

static int support_role_identity_threshold(const std::string& desired_role) {
    if (desired_role == "height") return 120;
    if (desired_role == "normal") return 96;
    if (desired_role == "material" || desired_role == "specular") return 88;
    if (desired_role == "detail") return 72;
    if (desired_role == "emissive") return 72;
    return 0;
}

static bool texture_family_clearly_matches_mesh(const std::string& texture_family_key, const NativeSubmesh& mesh) {
    if (texture_family_key.empty()) return false;
    const std::string mesh_material_key = normalized_material_key(mesh.material);
    const std::string mesh_name_key = normalized_material_key(mesh.name);
    return material_keys_match_for_identity(texture_family_key, mesh_material_key)
        || material_keys_match_for_identity(texture_family_key, mesh_name_key);
}

static bool native_base_text_has_any(const std::string& text, std::initializer_list<const char*> tokens) {
    for (const char* token : tokens) {
        if (text.find(token) != std::string::npos) return true;
    }
    return false;
}

static bool parameter_is_generic_color_texture_layer(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    if (key.find("colortexture") == std::string::npos) return false;
    if (
        key == "basecolortexture"
        || key == "diffusetexture"
        || key == "albedotexture"
        || key == "overlaycolortexture"
        || key.find("basecolor") != std::string::npos
        || key.find("diffuse") != std::string::npos
        || key.find("albedo") != std::string::npos
    ) {
        return false;
    }
    return true;
}

static bool base_binding_is_layer_albedo_candidate(const TextureBinding& binding) {
    const std::string role = lower_copy(binding.layer_role);
    const std::string parameter = normalized_key(binding.parameter_name);
    const std::string path_text = lower_copy(binding.archive_path + " " + binding.texture_name);
    if (role == "detail" || role == "grime" || role == "damage" || role == "layer") return true;
    if (binding.visible_class == "layer_visible") return true;
    if (parameter_is_generic_color_texture_layer(binding.parameter_name)) return true;
    if (native_base_text_has_any(parameter, {"grime", "detail", "damage", "dye", "layer", "blend", "decal"})) return true;
    if (path_text.find("texturelayer") != std::string::npos) return true;
    return false;
}

static bool base_binding_looks_like_layer_or_environment_albedo(const TextureBinding& binding) {
    const std::string text = lower_copy(
        binding.archive_path + " " + binding.texture_name + " " + binding.parameter_name + " " +
        binding.layer_role + " " + binding.visible_class
    );
    return native_base_text_has_any(text, {
        "texturelayer",
        "grime",
        "damage",
        "damaged",
        "scar",
        "wound",
        "blood",
        "detail",
        "floor",
        "soil",
        "ground",
        "terrain",
        "stone",
        "rock",
        "dirt",
        "mud",
        "sand",
        "grass",
        "akapen"
    });
}

static bool base_binding_texture_family_matches_mesh(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string texture_family_key = normalized_texture_family_key(
        binding.texture_name.empty() ? binding.archive_path : binding.texture_name
    );
    return texture_family_clearly_matches_mesh(texture_family_key, mesh);
}

static bool base_binding_is_wrong_family_layer_or_environment(const TextureBinding& binding, const NativeSubmesh& mesh) {
    return base_binding_looks_like_layer_or_environment_albedo(binding)
        && !base_binding_texture_family_matches_mesh(binding, mesh);
}

static bool mesh_looks_like_skin_surface(const NativeSubmesh& mesh) {
    const std::string text = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label);
    return native_base_text_has_any(text, {
        "nude",
        "skin",
        "body",
        "head",
        "hand",
        "face",
        "arm",
        "leg",
        "foot"
    });
}

static bool selected_base_is_semantically_unsafe_skin_albedo(const TextureBinding& binding, const NativeSubmesh& mesh) {
    return mesh_looks_like_skin_surface(mesh)
        && base_binding_is_wrong_family_layer_or_environment(binding, mesh);
}

static bool base_binding_has_unsafe_cross_part_texture_family(const TextureBinding& binding, const NativeSubmesh& mesh) {
    if (material_wrapper_matches_mesh_local_index(binding, mesh)) return false;
    const std::string texture_family_key = normalized_texture_family_key(binding.texture_name.empty() ? binding.archive_path : binding.texture_name);
    if (!material_identity_has_conflicting_specific_part(
        texture_family_key,
        normalized_material_key(mesh.material),
        normalized_material_key(mesh.name))) {
        return false;
    }
    return !texture_family_clearly_matches_mesh(texture_family_key, mesh);
}

static bool binding_is_overlay_base_fallback_candidate(const TextureBinding& binding, const NativeSubmesh& mesh) {
    if (binding.source_path.empty() || binding.role != "base") return false;
    if (placeholder_visible_base_path(binding.archive_path) || placeholder_visible_base_path(binding.texture_name)) return false;
    if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)) return false;
    if (dds_format_is_data_only_for_visible_base(binding.dds_format)) return false;
    const std::string parameter_key = normalized_key(binding.parameter_name);
    const bool overlay_hint =
        parameter_key.find("overlaycolor") != std::string::npos
        || low_authority_base_path(binding.archive_path)
        || low_authority_base_path(binding.texture_name);
    if (!overlay_hint) return false;
    if (!material_binding_matches_mesh_source(binding, mesh)) return false;
    const int identity_score = material_identity_match_score(binding, mesh);
    if (!material_wrapper_matches_mesh_local_index(binding, mesh) && identity_score < 300) return false;
    if (base_binding_has_unsafe_cross_part_texture_family(binding, mesh)) return false;
    return true;
}

static bool binding_is_authoritative_same_family_overlay_base(const TextureBinding& binding, const NativeSubmesh& mesh) {
    if (!binding_is_overlay_base_fallback_candidate(binding, mesh)) return false;
    if (binding.source_authority != "exact_sidecar") return false;
    if (normalized_key(binding.parameter_name).find("overlaycolor") == std::string::npos) return false;
    return base_binding_texture_family_matches_mesh(binding, mesh);
}

static bool mesh_has_apparel_slot_surface_for_base_selection(const NativeSubmesh& mesh) {
    std::string evidence = lower_copy(mesh.material + " " + mesh.name + " " + mesh.source_component_label + " " + mesh.source_model_path);
    std::replace(evidence.begin(), evidence.end(), '\\', '/');
    return evidence.find("/9_upperbody/") != std::string::npos
        || evidence.find("/10_lowerbody/") != std::string::npos
        || evidence.find("_ub_") != std::string::npos
        || evidence.find("_lb_") != std::string::npos
        || evidence.find("upperbody") != std::string::npos
        || evidence.find("lowerbody") != std::string::npos
        || evidence.find("pants") != std::string::npos
        || evidence.find("trouser") != std::string::npos
        || evidence.find("skirt") != std::string::npos
        || evidence.find("dress") != std::string::npos
        || evidence.find("tunic") != std::string::npos
        || evidence.find("sleeve") != std::string::npos;
}

static bool binding_is_primary_apparel_base_color(const TextureBinding& binding) {
    const std::string parameter = normalized_key(binding.parameter_name);
    if (base_binding_is_low_authority_overlay(&binding)) return false;
    return binding.visible_class == "primary_visible"
        || parameter.find("basecolor") != std::string::npos
        || parameter.find("diffusetexture") != std::string::npos
        || parameter.find("albedotexture") != std::string::npos;
}

static bool selected_base_should_yield_to_overlay(
    const TextureBinding* selected,
    const TextureBinding& overlay,
    const NativeSubmesh& mesh,
    int selected_score,
    int overlay_score
) {
    if (selected == nullptr) return true;
    if (!binding_is_authoritative_same_family_overlay_base(overlay, mesh)) return false;
    if (mesh_has_apparel_slot_surface_for_base_selection(mesh) && binding_is_primary_apparel_base_color(*selected)) {
        return false;
    }
    const bool selected_wrong_layer = base_binding_is_wrong_family_layer_or_environment(*selected, mesh);
    const bool selected_texture_layer = lower_copy(selected->archive_path + " " + selected->texture_name).find("texturelayer") != std::string::npos;
    return selected_wrong_layer || (selected_texture_layer && overlay_score >= selected_score - 180);
}

static const TextureBinding* best_overlay_base_fallback(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    int* selected_score = nullptr
) {
    const TextureBinding* best = nullptr;
    int best_score = -100000;
    for (const TextureBinding& binding : bindings) {
        if (!binding_is_overlay_base_fallback_candidate(binding, mesh)) continue;
        const int identity_score = material_identity_match_score(binding, mesh);
        int score = material_match_score(binding, mesh, "base") + identity_score / 2;
        score += visible_class_priority(binding.visible_class) * 18;
        if (material_wrapper_matches_mesh_local_index(binding, mesh)) score += 280;
        if (binding.source_authority == "exact_sidecar") score += 160;
        if (binding.source_authority == "embedded_mesh") score += 120;
        if (normalized_key(binding.parameter_name).find("overlaycolor") != std::string::npos) score += 80;
        if (base_binding_texture_family_matches_mesh(binding, mesh)) score += 90;
        const int largest_dimension = std::max(binding.dds_width, binding.dds_height);
        if (largest_dimension >= 1024) score += 42;
        else if (largest_dimension >= 512) score += 20;
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    if (selected_score != nullptr) *selected_score = best == nullptr ? 0 : best_score;
    return best;
}

static void append_rejected_binding_example(
    std::vector<std::string>* rejected_examples,
    const std::string& desired_role,
    const std::string& reason,
    const TextureBinding& binding,
    const NativeSubmesh& mesh,
    int identity_score = -1
) {
    if (rejected_examples == nullptr || rejected_examples->size() >= 16) return;
    std::string text =
        desired_role + " rejected " + reason + " candidate "
        + (binding.texture_name.empty() ? basename_from_path(binding.archive_path) : binding.texture_name)
        + " for " + mesh.material;
    if (identity_score >= 0) {
        text += " identity=" + std::to_string(identity_score);
    }
    rejected_examples->push_back(text);
}
