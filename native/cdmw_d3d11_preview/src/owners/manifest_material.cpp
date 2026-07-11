static std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

static std::string normalize_display_mode(std::string value, const std::string& fallback = "replacement_only") {
    value = lower_copy(std::move(value));
    if (value == "side_by_side" || value == "overlay" || value == "replacement_only" || value == "original_only") {
        return value;
    }
    return fallback == "side_by_side" || fallback == "overlay" || fallback == "replacement_only" || fallback == "original_only" ? fallback : "replacement_only";
}

static std::string parse_display_mode(const std::string& manifest, const std::string& fallback = "replacement_only") {
    return normalize_display_mode(json_string_field(manifest, "display_mode", fallback), fallback);
}

static bool contains_text(const std::string& haystack, const std::string& needle) {
    return haystack.find(needle) != std::string::npos;
}

static bool looks_like_path_suffix(const std::string& source_path, const std::string& suffix) {
    std::string lower = lower_copy(source_path);
    size_t slash = lower.find_last_of("/\\");
    std::string name = slash == std::string::npos ? lower : lower.substr(slash + 1);
    if (name.size() >= suffix.size() + 4 && name.ends_with(suffix + ".dds")) return true;
    if (name.size() >= suffix.size() && name.ends_with(suffix)) return true;
    return false;
}

static int material_dds_candidate_score(const std::string& object, const std::string& role) {
    std::string source_path = json_string_field(object, "source_path");
    if (source_path.empty()) return -1000;
    if (!json_bool_field(object, "available", true)) return -1000;
    std::string slot = lower_copy(json_string_field(object, "slot"));
    std::string parameter = lower_copy(json_string_field(object, "parameter_name"));
    std::string semantic_type = lower_copy(json_string_field(object, "semantic_type"));
    std::string semantic_subtype = lower_copy(json_string_field(object, "semantic_subtype"));
    std::string descriptor = lower_copy(source_path + " " + slot + " " + parameter + " " + semantic_type + " " + semantic_subtype);
    int dimension_bonus = 0;
    int largest_dimension = std::max(json_int_field(object, "width", 0), json_int_field(object, "height", 0));
    if (largest_dimension >= 2048) dimension_bonus = 18;
    else if (largest_dimension >= 1024) dimension_bonus = 14;
    else if (largest_dimension >= 512) dimension_bonus = 8;

    if (role == "base") {
        int score = -1000;
        if (contains_text(descriptor, "normal") || looks_like_path_suffix(source_path, "_n")) score -= 240;
        if (contains_text(descriptor, "height") || contains_text(descriptor, "displacement") || looks_like_path_suffix(source_path, "_disp")) score -= 240;
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "alpha")) score -= 220;
        if (looks_like_path_suffix(source_path, "_ma") || looks_like_path_suffix(source_path, "_mg") || looks_like_path_suffix(source_path, "_sp")) score -= 220;
        if (looks_like_path_suffix(source_path, "_o")) score = std::max(score, 118);
        if (contains_text(parameter, "basecolor") || contains_text(parameter, "diffuse") || contains_text(parameter, "albedo")) score = std::max(score, 108);
        if (contains_text(parameter, "overlaycolor") || contains_text(parameter, "colorlayer")) score = std::max(score, 92);
        if (semantic_type == "base" || semantic_type == "albedo" || semantic_type == "diffuse" || semantic_subtype == "base_color") score = std::max(score, 104);
        if (slot == "base") score = std::max(score, 96);
        if (contains_text(descriptor, "texturelayer") && score < 80) score = std::max(score, 70);
        if (score > -1000) score += dimension_bonus;
        return score;
    }
    if (role == "specular") {
        int score = -1000;
        if (looks_like_path_suffix(source_path, "_sp")) score = std::max(score, 110);
        if (contains_text(parameter, "specular")) score = std::max(score, 100);
        if (semantic_subtype == "specular" || semantic_type == "specular") score = std::max(score, 96);
        if (contains_text(descriptor, "gloss") || contains_text(descriptor, "smoothness")) score = std::max(score, 76);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "roughness") {
        int score = -1000;
        if (contains_text(parameter, "roughness") || semantic_subtype == "roughness" || semantic_type == "roughness") score = std::max(score, 100);
        if (contains_text(descriptor, "gloss") || contains_text(descriptor, "smoothness")) score -= 220;
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "metalness") {
        int score = -1000;
        if (contains_text(parameter, "metallic") || contains_text(parameter, "metalness")) score = std::max(score, 100);
        if (semantic_subtype == "metallic" || semantic_subtype == "metalness" || semantic_type == "metallic") score = std::max(score, 96);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "occlusion") {
        int score = -1000;
        if (contains_text(parameter, "occlusion") || semantic_subtype == "ao" || semantic_subtype == "ambient_occlusion") score = std::max(score, 96);
        if (looks_like_path_suffix(source_path, "_ao")) score = std::max(score, 86);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "material") {
        int score = -1000;
        if (looks_like_path_suffix(source_path, "_ma")) score = std::max(score, 112);
        if (semantic_subtype == "material_mask" || semantic_subtype == "material_response" || semantic_subtype == "packed_mask") score = std::max(score, 100);
        if (contains_text(parameter, "materialtexture") || contains_text(parameter, "materialmask")) score = std::max(score, 92);
        if (looks_like_path_suffix(source_path, "_m")) score = std::max(score, 72);
        if (looks_like_path_suffix(source_path, "_mg") || contains_text(parameter, "detailmask") || contains_text(parameter, "colorblendingmask")) score = std::max(score, 28);
        if (contains_text(descriptor, "specular") || looks_like_path_suffix(source_path, "_sp")) score -= 120;
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "detail") {
        int score = -1000;
        if (looks_like_path_suffix(source_path, "_mg")) score = std::max(score, 108);
        if (contains_text(parameter, "detailmask")) score = std::max(score, 104);
        if (contains_text(parameter, "colorblendingmask")) score = std::max(score, 96);
        if (semantic_subtype == "detail_mask" || semantic_type == "detail_mask") score = std::max(score, 96);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        if (score > -1000) score += dimension_bonus / 2;
        return score;
    }
    return -1000;
}

static std::wstring best_material_dds_for_role(const std::string& object, const std::string& role) {
    int best_score = -1000;
    std::string best_path;
    for (const std::string& candidate : objects_with_key(object, "source_path")) {
        int score = material_dds_candidate_score(candidate, role);
        if (score > best_score) {
            std::string source_path = json_string_field(candidate, "source_path");
            if (!source_path.empty()) {
                best_score = score;
                best_path = source_path;
            }
        }
    }
    int minimum_score = 40;
    if (role == "base") minimum_score = 58;
    else if (role == "detail") minimum_score = 32;
    if (best_score < minimum_score || best_path.empty()) return L"";
    return utf8_to_wide(best_path);
}

static float material_layer_channel_index(const std::string& channel) {
    std::string value = lower_copy(channel);
    if (value == "g") return 1.0f;
    if (value == "b") return 2.0f;
    if (value == "a") return 3.0f;
    return 0.0f;
}

static void parse_material_layer_object(PreviewMaterialLayer& layer, const std::string& object) {
    layer.role = json_string_field(object, "layer_role");
    layer.evidence_grade = json_string_field(object, "evidence_grade");
    layer.channel_index = material_layer_channel_index(json_string_field(object, "mask_channel", "r"));
    layer.weight = std::clamp(json_float_field(object, "weight", 0.0f), 0.0f, 1.0f);
    layer.diffuse_dds = utf8_to_wide(json_string_field(object, "diffuse_source"));
    layer.mask_dds = utf8_to_wide(json_string_field(object, "mask_source"));
    layer.material_dds = utf8_to_wide(json_string_field(object, "material_source"));
    layer.normal_dds = utf8_to_wide(json_string_field(object, "normal_source"));
    layer.height_dds = utf8_to_wide(json_string_field(object, "height_source"));
    layer.roughness_hint = std::clamp(json_float_field(object, "roughness_hint", 0.0f), 0.0f, 1.0f);
    layer.metalness_hint = std::clamp(json_float_field(object, "metalness_hint", 0.0f), 0.0f, 1.0f);
    layer.specular_hint = std::clamp(json_float_field(object, "specular_hint", 0.0f), 0.0f, 1.0f);
    layer.height_scale_hint = std::clamp(json_float_field(object, "height_scale_hint", 0.0f), 0.0f, 1.0f);
    const std::vector<float> tint = json_float_array_field(object, "tint");
    for (size_t index = 0; index < std::min<size_t>(4, tint.size()); ++index) {
        layer.tint[index] = std::clamp(tint[index], 0.0f, 2.0f);
    }
}

static void append_batch_material_layer(PreviewBatch& batch, const PreviewMaterialLayer& layer) {
    if (batch.material_layer_count >= kMaxMaterialLayers) return;
    if (layer.diffuse_dds.empty()) return;
    const std::string role = lower_copy(layer.role);
    if (role.empty() || role == "base") return;
    batch.material_layers[static_cast<size_t>(batch.material_layer_count)] = layer;
    ++batch.material_layer_count;
}

static void parse_material_layers(PreviewBatch& batch, const std::string& object) {
    for (const std::string& layer_object : json_object_array_field(object, "material_layers")) {
        PreviewMaterialLayer layer;
        parse_material_layer_object(layer, layer_object);
        append_batch_material_layer(batch, layer);
    }
}

static void parse_primary_material_layer(PreviewBatch& batch, const std::string& object) {
    const std::string layer = json_object_field(object, "primary_material_layer");
    if (layer.empty() || !json_bool_field(layer, "active", false)) return;
    batch.layer_role = json_string_field(layer, "layer_role");
    batch.layer_evidence_grade = json_string_field(layer, "evidence_grade");
    batch.layer_channel_index = material_layer_channel_index(json_string_field(layer, "mask_channel", "r"));
    batch.layer_weight = std::clamp(json_float_field(layer, "weight", 0.0f), 0.0f, 1.0f);
    batch.layer_diffuse_dds = utf8_to_wide(json_string_field(layer, "diffuse_source"));
    batch.layer_mask_dds = utf8_to_wide(json_string_field(layer, "mask_source"));
    batch.layer_material_dds = utf8_to_wide(json_string_field(layer, "material_source"));
    batch.layer_normal_dds = utf8_to_wide(json_string_field(layer, "normal_source"));
    batch.layer_height_dds = utf8_to_wide(json_string_field(layer, "height_source"));
    batch.layer_roughness_hint = std::clamp(json_float_field(layer, "roughness_hint", 0.0f), 0.0f, 1.0f);
    batch.layer_metalness_hint = std::clamp(json_float_field(layer, "metalness_hint", 0.0f), 0.0f, 1.0f);
    batch.layer_specular_hint = std::clamp(json_float_field(layer, "specular_hint", 0.0f), 0.0f, 1.0f);
    batch.layer_height_scale_hint = std::clamp(json_float_field(layer, "height_scale_hint", 0.0f), 0.0f, 1.0f);
    const std::vector<float> tint = json_float_array_field(layer, "tint");
    for (size_t index = 0; index < std::min<size_t>(4, tint.size()); ++index) {
        batch.layer_tint[index] = std::clamp(tint[index], 0.0f, 2.0f);
    }
    if (batch.material_layer_count == 0) {
        PreviewMaterialLayer compat_layer;
        compat_layer.role = batch.layer_role;
        compat_layer.evidence_grade = batch.layer_evidence_grade;
        compat_layer.channel_index = batch.layer_channel_index;
        compat_layer.weight = batch.layer_weight;
        compat_layer.diffuse_dds = batch.layer_diffuse_dds;
        compat_layer.mask_dds = batch.layer_mask_dds;
        compat_layer.material_dds = batch.layer_material_dds;
        compat_layer.normal_dds = batch.layer_normal_dds;
        compat_layer.height_dds = batch.layer_height_dds;
        compat_layer.roughness_hint = batch.layer_roughness_hint;
        compat_layer.metalness_hint = batch.layer_metalness_hint;
        compat_layer.specular_hint = batch.layer_specular_hint;
        compat_layer.height_scale_hint = batch.layer_height_scale_hint;
        for (size_t i = 0; i < 4; ++i) compat_layer.tint[i] = batch.layer_tint[i];
        append_batch_material_layer(batch, compat_layer);
    }
}

static void increment_slot(SlotCounts& counts, const std::string& slot) {
    if (slot == "base") ++counts.base;
    else if (slot == "normal") ++counts.normal;
    else if (slot == "material") ++counts.material;
    else if (slot == "height") ++counts.height;
    else if (slot == "occlusion") ++counts.occlusion;
    else if (slot == "roughness") ++counts.roughness;
    else if (slot == "metalness") ++counts.metalness;
    else if (slot == "specular") ++counts.specular;
    else if (slot == "detail" || slot == "layer_base") ++counts.detail;
    else if (slot == "emissive") ++counts.emissive;
}

static std::string slot_counts_json(const SlotCounts& counts) {
    std::ostringstream out;
    out << "{"
        << "\"base\":" << counts.base
        << ",\"normal\":" << counts.normal
        << ",\"material\":" << counts.material
        << ",\"height\":" << counts.height
        << ",\"occlusion\":" << counts.occlusion
        << ",\"roughness\":" << counts.roughness
        << ",\"metalness\":" << counts.metalness
        << ",\"specular\":" << counts.specular
        << ",\"detail\":" << counts.detail
        << ",\"emissive\":" << counts.emissive
        << "}";
    return out.str();
}

static std::string string_int_map_json(const std::map<std::string, int>& values) {
    std::ostringstream out;
    out << "{";
    size_t index = 0;
    for (const auto& [key, value] : values) {
        if (index++) out << ",";
        out << "\"" << json_escape(key) << "\":" << value;
    }
    out << "}";
    return out.str();
}

static std::string dxgi_format_name(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_BC1_UNORM: return "DXGI_FORMAT_BC1_UNORM";
    case DXGI_FORMAT_BC1_UNORM_SRGB: return "DXGI_FORMAT_BC1_UNORM_SRGB";
    case DXGI_FORMAT_BC2_UNORM: return "DXGI_FORMAT_BC2_UNORM";
    case DXGI_FORMAT_BC2_UNORM_SRGB: return "DXGI_FORMAT_BC2_UNORM_SRGB";
    case DXGI_FORMAT_BC3_UNORM: return "DXGI_FORMAT_BC3_UNORM";
    case DXGI_FORMAT_BC3_UNORM_SRGB: return "DXGI_FORMAT_BC3_UNORM_SRGB";
    case DXGI_FORMAT_BC4_UNORM: return "DXGI_FORMAT_BC4_UNORM";
    case DXGI_FORMAT_BC4_SNORM: return "DXGI_FORMAT_BC4_SNORM";
    case DXGI_FORMAT_BC5_UNORM: return "DXGI_FORMAT_BC5_UNORM";
    case DXGI_FORMAT_BC5_SNORM: return "DXGI_FORMAT_BC5_SNORM";
    case DXGI_FORMAT_BC6H_UF16: return "DXGI_FORMAT_BC6H_UF16";
    case DXGI_FORMAT_BC6H_SF16: return "DXGI_FORMAT_BC6H_SF16";
    case DXGI_FORMAT_BC7_UNORM: return "DXGI_FORMAT_BC7_UNORM";
    case DXGI_FORMAT_BC7_UNORM_SRGB: return "DXGI_FORMAT_BC7_UNORM_SRGB";
    case DXGI_FORMAT_R8G8B8A8_UNORM: return "DXGI_FORMAT_R8G8B8A8_UNORM";
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: return "DXGI_FORMAT_R8G8B8A8_UNORM_SRGB";
    default: return "DXGI_FORMAT_" + std::to_string(static_cast<unsigned int>(format));
    }
}

static void parse_float3_array_field(const std::string& object, const std::string& field_name, float out_color[3]) {
    std::regex pattern("\"" + field_name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return;
    std::string values = match[1].str();
    std::regex number_pattern("-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");
    auto begin = std::sregex_iterator(values.begin(), values.end(), number_pattern);
    auto end = std::sregex_iterator();
    int index = 0;
    for (auto it = begin; it != end && index < 3; ++it, ++index) {
        try {
            out_color[index] = std::clamp(std::stof(it->str()), 0.0f, 1.5f);
        } catch (...) {
        }
    }
}

static void parse_base_color(const std::string& object, float out_color[3]) {
    parse_float3_array_field(object, "base_color", out_color);
}

static float material_family_code(const std::string& shader_family) {
    const std::string family = lower_copy(shader_family);
    if (family == "skin") return 1.0f;
    if (family == "hair") return 2.0f;
    if (family == "cloth" || family == "cloth_v2") return 3.0f;
    if (family == "standard" || family == "standard_v2") return 4.0f;
    if (family == "static_standard" || family == "static_multitextured") return 5.0f;
    if (family == "emissive" || family == "emissive_v2") return 6.0f;
    return 0.0f;
}

static float material_category_code(const std::string& category) {
    const std::string value = lower_copy(category);
    if (value == "metal") return 1.0f;
    if (value == "leather") return 2.0f;
    if (value == "wood") return 3.0f;
    if (value == "cloth") return 4.0f;
    if (value == "skin") return 5.0f;
    if (value == "hair") return 6.0f;
    if (value == "glass") return 7.0f;
    if (value == "gem") return 8.0f;
    if (value == "stone") return 9.0f;
    if (value == "eye") return 10.0f;
    if (value == "tooth") return 11.0f;
    return 0.0f;
}

static float boosted_preview_layer_weight(const PreviewMaterialLayer& layer, int layer_index) {
    (void)layer_index;
    return std::clamp(layer.weight, 0.0f, 1.0f);
}

static void parse_manifest_batch_material(
    PreviewBatch& batch,
    const fs::path& package_dir,
    const std::string& object,
    int fallback_index) {
        batch.index = json_int_field(object, "index", fallback_index);
        batch.vertex_count = json_int_field(object, "vertex_count", 0);
        batch.flip_v = json_bool_field(object, "texture_flip_vertical", false);
        batch.alpha_cutout = lower_copy(json_string_field(object, "alpha_mode")).find("cutout") != std::string::npos;
        batch.two_sided = json_bool_field(object, "two_sided", json_bool_field(object, "double_sided", false));
        batch.alpha_threshold = std::clamp(json_float_field(object, "alpha_threshold", batch.alpha_cutout ? 0.12f : 0.0f), 0.0f, 0.95f);
        const std::string normal_y_policy = lower_copy(json_string_field(object, "normal_y_policy"));
        batch.invert_normal_y = normal_y_policy.empty()
            || normal_y_policy.find("invert") != std::string::npos
            || normal_y_policy.find("legacy") != std::string::npos;
        parse_base_color(object, batch.base_color);
        batch.vertex_file = absolute_from_manifest_path(package_dir, json_string_field(object, "vertex_file"));
        batch.vertex_offset = json_uint64_field(object, "vertex_offset", 0);
        batch.vertex_size = json_uint64_field(object, "vertex_size", 0);
        batch.base_dds = dds_slot_source(object, "base");
        batch.normal_dds = dds_slot_source(object, "normal");
        batch.material_dds = dds_slot_source(object, "material");
        if (batch.material_dds.empty()) batch.material_dds = best_material_dds_for_role(object, "material");
        batch.occlusion_dds = best_material_dds_for_role(object, "occlusion");
        batch.roughness_dds = best_material_dds_for_role(object, "roughness");
        batch.metalness_dds = best_material_dds_for_role(object, "metalness");
        batch.specular_dds = best_material_dds_for_role(object, "specular");
        batch.detail_dds = best_material_dds_for_role(object, "detail");
        batch.height_dds = dds_slot_source(object, "height");
        batch.emissive_dds = dds_slot_source(object, "emissive");
        batch.base_png = texture_slot_relative(package_dir, object, "base");
        batch.normal_png = texture_slot_relative(package_dir, object, "normal");
        batch.occlusion_png = texture_slot_relative(package_dir, object, "occlusion");
        batch.roughness_png = texture_slot_relative(package_dir, object, "roughness");
        batch.metalness_png = texture_slot_relative(package_dir, object, "metalness");
        batch.specular_png = texture_slot_relative(package_dir, object, "specular");
        batch.height_png = texture_slot_relative(package_dir, object, "height");
        batch.emissive_png = texture_slot_relative(package_dir, object, "emissive");
        if (json_bool_field(object, "prefer_generated_base_texture", false) && !batch.base_png.empty()) {
            batch.base_dds.clear();
        }
        batch.normal_strength = std::clamp(json_float_field(object, "normal_strength", 1.0f), 0.0f, 2.0f);
        batch.height_amount = std::clamp(json_float_field(object, "height_amount", 0.0f), 0.0f, 0.16f);
        batch.roughness_hint = std::clamp(json_float_field(object, "roughness", 0.0f), 0.0f, 1.0f);
        batch.metalness_hint = std::clamp(json_float_field(object, "metalness", 0.0f), 0.0f, 1.0f);
        batch.specular_hint = std::clamp(json_float_field(object, "specular", 0.0f), 0.0f, 1.0f);
        batch.height_scale_hint = std::clamp(json_float_field(object, "height_scale", 0.0f), 0.0f, 1.0f);
        batch.emissive_intensity = std::clamp(json_float_field(object, "emissive_intensity", 0.0f), 0.0f, 32.0f);
        parse_float3_array_field(object, "emissive_color", batch.emissive_color);
        batch.highlight_strength = std::clamp(json_float_field(object, "highlight_strength", 0.0f), 0.0f, 1.0f);
        batch.base_tint_strength = std::clamp(json_float_field(object, "base_tint_strength", 0.0f), 0.0f, 1.0f);
        batch.texture_brightness = std::clamp(json_float_field(object, "texture_brightness", 1.0f), 0.1f, 3.0f);
        batch.texture_contrast = std::clamp(json_float_field(object, "texture_contrast", 1.0f), 0.25f, 2.5f);
        batch.texture_saturation = std::clamp(json_float_field(object, "texture_saturation", 1.0f), 0.0f, 4.0f);
        batch.texture_gamma = std::clamp(json_float_field(object, "texture_gamma", 1.0f), 0.25f, 4.0f);
        parse_float3_array_field(object, "texture_tint", batch.texture_tint);
        const std::vector<float> texture_uv_scale = json_float_array_field(object, "texture_uv_scale");
        if (!texture_uv_scale.empty()) {
            batch.texture_uv_scale[0] = std::clamp(texture_uv_scale[0], 0.05f, 64.0f);
            batch.texture_uv_scale[1] = texture_uv_scale.size() > 1
                ? std::clamp(texture_uv_scale[1], 0.05f, 64.0f)
                : batch.texture_uv_scale[0];
        }
        batch.material_shader_family = lower_copy(json_string_field(object, "material_shader_family"));
        if (batch.material_shader_family.empty()) {
            batch.material_shader_family = lower_copy(json_string_field(object, "shader_rule"));
        }
        if (batch.material_shader_family.empty()) {
            batch.material_shader_family = lower_copy(json_string_field(object, "shader_family", "generic"));
        }
        batch.material_family_code = material_family_code(batch.material_shader_family);
        batch.material_category_code = material_category_code(json_string_field(object, "material_category", "generic"));
        batch.material_category_confidence = std::clamp(json_float_field(object, "material_category_confidence", 0.35f), 0.0f, 1.0f);
        batch.material_response_promoted = json_bool_field(object, "material_response_promoted", false);
        batch.low_authority_base_overlay = json_bool_field(object, "base_low_authority_overlay", false);
        parse_material_layers(batch, object);
        parse_primary_material_layer(batch, object);
}

static void parse_manifest_batch_identity_and_cloth(
    PreviewBatch& batch,
    const fs::path& package_dir,
    const std::string& object,
    const std::vector<float>& normalization_center,
    float normalization_scale,
    RendererStats& stats) {
        std::string editor_identity = json_object_field(object, "editor_identity");
        batch.source_submesh_index = json_int_field(editor_identity, "source_submesh_index", -1);
        batch.source_local_submesh_index = json_int_field(editor_identity, "source_local_submesh_index", batch.source_submesh_index);
        batch.source_component_index = json_int_field(editor_identity, "source_component_index", 0);
        batch.source_vertex_count = json_int_field(editor_identity, "source_vertex_count", 0);
        batch.source_face_count = json_int_field(editor_identity, "source_face_count", 0);
        batch.identity_file = absolute_from_manifest_path(package_dir, json_string_field(editor_identity, "identity_file"));
        batch.identity_offset = json_uint64_field(editor_identity, "identity_offset", 0);
        batch.identity_size = json_uint64_field(editor_identity, "identity_size", 0);
        batch.identity_stride_bytes = json_uint64_field(editor_identity, "identity_stride_bytes", 0);
        batch.source_model_path = json_string_field(editor_identity, "source_model_path");
        batch.source_component_label = json_string_field(editor_identity, "source_component_label");
        batch.part_label = json_string_field(editor_identity, "part_label");
        batch.prefab_component = json_bool_field(editor_identity, "prefab_component", false);
        batch.editor_role = lower_copy(json_string_field(editor_identity, "role"));
        batch.editor_editable = json_bool_field(editor_identity, "editable", batch.source_submesh_index >= 0);
        batch.normalization_center[0] = normalization_center.size() > 0u ? normalization_center[0] : 0.0f;
        batch.normalization_center[1] = normalization_center.size() > 1u ? normalization_center[1] : 0.0f;
        batch.normalization_center[2] = normalization_center.size() > 2u ? normalization_center[2] : 0.0f;
        batch.normalization_scale = normalization_scale;
        if (batch.editor_role.find("original") != std::string::npos
            || batch.editor_role.find("reference") != std::string::npos) {
            batch.editor_editable = false;
        }
        batch.cloth.available = json_bool_field(object, "cloth_enabled", false);
        if (batch.cloth.available) {
            batch.cloth.kind = lower_copy(json_string_field(object, "cloth_kind", "cloth"));
            batch.cloth.material_name = json_string_field(object, "cloth_material_name");
            batch.cloth.particle_file = absolute_from_manifest_path(package_dir, json_string_field(object, "cloth_particle_file"));
            batch.cloth.pin_file = absolute_from_manifest_path(package_dir, json_string_field(object, "cloth_pin_file"));
            batch.cloth.constraint_file = absolute_from_manifest_path(package_dir, json_string_field(object, "cloth_constraint_file"));
            batch.cloth.particle_count = std::max(0, json_int_field(object, "cloth_particle_count", 0));
            batch.cloth.constraint_count = std::max(0, json_int_field(object, "cloth_constraint_count", 0));
            batch.cloth.gravity = std::clamp(json_float_field(object, "cloth_gravity", -10.0f), -50.0f, 50.0f);
            batch.cloth.damping = std::clamp(json_float_field(object, "cloth_damping", 0.65f), 0.0f, 4.0f);
            batch.cloth.air_resistance = std::clamp(json_float_field(object, "cloth_air_resistance", 1.0f), 0.0f, 8.0f);
            batch.cloth.wind_response = std::clamp(json_float_field(object, "cloth_wind_response", 0.4f), 0.0f, 4.0f);
            batch.cloth.solver_iterations = std::clamp(json_int_field(object, "cloth_solver_iterations", 30), 1, 64);
            batch.cloth.collision_enabled = json_bool_field(object, "cloth_collision_enabled", true);
            ++stats.cloth_batch_count;
            stats.cloth_particle_count += batch.cloth.particle_count;
            stats.cloth_constraint_count += batch.cloth.constraint_count;
        }
}

static void record_manifest_batch_stats(
    const PreviewBatch& batch,
    const std::string& object,
    RendererStats& stats) {
        if (!batch.base_dds.empty()) increment_slot(stats.dds_candidates, "base");
        if (!batch.normal_dds.empty()) increment_slot(stats.dds_candidates, "normal");
        if (!batch.material_dds.empty()) increment_slot(stats.dds_candidates, "material");
        if (!batch.occlusion_dds.empty()) increment_slot(stats.dds_candidates, "occlusion");
        if (!batch.roughness_dds.empty()) increment_slot(stats.dds_candidates, "roughness");
        if (!batch.metalness_dds.empty()) increment_slot(stats.dds_candidates, "metalness");
        if (!batch.specular_dds.empty()) increment_slot(stats.dds_candidates, "specular");
        if (!batch.detail_dds.empty()) increment_slot(stats.dds_candidates, "detail");
        if (!batch.height_dds.empty()) increment_slot(stats.dds_candidates, "height");
        if (!batch.emissive_dds.empty()) increment_slot(stats.dds_candidates, "emissive");
        for (int layer_index = 0; layer_index < batch.material_layer_count; ++layer_index) {
            const PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
            if (!layer.diffuse_dds.empty()) increment_slot(stats.dds_candidates, "detail");
            if (!layer.mask_dds.empty()) increment_slot(stats.dds_candidates, "detail");
            if (!layer.material_dds.empty()) increment_slot(stats.dds_candidates, "material");
            if (!layer.normal_dds.empty()) increment_slot(stats.dds_candidates, "normal");
            if (!layer.height_dds.empty()) increment_slot(stats.dds_candidates, "height");
            ++stats.material_layer_count;
            ++stats.material_layer_roles[layer.role.empty() ? "layer" : lower_copy(layer.role)];
        }
        if (batch.material_layer_count > 0) {
            ++stats.material_layer_active_batches;
        }
        if (json_bool_field(object, "material_combiner_active", false)) {
            ++stats.material_combiner_active_batches;
        }
        for (const std::string& output : json_string_array_field(object, "material_combiner_outputs")) {
            ++stats.material_combiner_outputs[output];
        }
        for (const std::string& mode : json_string_array_field(object, "material_combiner_decode_modes")) {
            ++stats.material_combiner_decode_modes[mode];
        }
}

static bool parse_manifest_metadata(
    const std::string& manifest,
    std::vector<PreviewBatch>& batches,
    RendererStats& stats) {
    stats.batch_count = static_cast<int>(batches.size());
    stats.vertex_count = json_int_field(manifest, "vertex_count", 0);
    stats.cloth_collider_count = std::max(0, json_int_field(manifest, "cloth_collider_count", 0));
    stats.pbd_hint_count = std::max(0, json_int_field(manifest, "pbd_hint_count", 0));
    stats.pbd_soft_hint_count = std::max(0, json_int_field(manifest, "pbd_soft_hint_count", 0));
    stats.pbd_cloth_hint_count = std::max(0, json_int_field(manifest, "pbd_cloth_hint_count", 0));
    stats.manifest_schema_version = std::max(0, json_int_field(manifest, "schema_version", 0));
    stats.material_contract_schema = std::max(0, json_int_field(manifest, "material_contract_schema", 0));
    stats.material_channel_contract_schema = std::max(0, json_int_field(manifest, "material_channel_contract_schema", 0));
    stats.texture_quality_schema = std::max(0, json_int_field(manifest, "texture_quality_schema", 0));
    stats.cloth_runtime_schema = std::max(0, json_int_field(manifest, "cloth_runtime_schema", 0));
    const auto reject_schema = [&](bool invalid, const char* reason) {
        if (!invalid) return false;
        stats.skipped.push_back(reason);
        batches.clear();
        return true;
    };
    if (reject_schema(
            stats.manifest_schema_version < kMinSupportedPreviewSchemaVersion
                || stats.manifest_schema_version > kMaxSupportedPreviewSchemaVersion,
            "unsupported manifest schema_version")
        || reject_schema(
            stats.material_contract_schema != 0
                && stats.material_contract_schema != kSupportedMaterialContractSchemaVersion,
            "unsupported material_contract_schema")
        || reject_schema(
            stats.material_channel_contract_schema != 0
                && stats.material_channel_contract_schema != kSupportedMaterialChannelContractSchemaVersion,
            "unsupported material_channel_contract_schema")
        || reject_schema(
            stats.texture_quality_schema != 0
                && stats.texture_quality_schema != kSupportedTextureQualitySchemaVersion,
            "unsupported texture_quality_schema")) {
        return false;
    }
    stats.render_diagnostic_mode = json_string_field(manifest, "d3d11_view_mode");
    if (stats.render_diagnostic_mode.empty()) {
        stats.render_diagnostic_mode = json_string_field(manifest, "render_diagnostic_mode");
    }
    stats.lighting_preset = json_string_field(manifest, "lighting_preset");
    return true;
}

static std::vector<PreviewBatch> parse_manifest_batches(const fs::path& package_dir, const std::string& manifest, RendererStats& stats) {
    std::vector<PreviewBatch> batches;
    const std::vector<float> manifest_normalization_center = json_float_array_field(manifest, "normalization_center");
    float manifest_normalization_scale = json_float_field(manifest, "normalization_scale", 1.0f);
    if (!std::isfinite(manifest_normalization_scale) || std::abs(manifest_normalization_scale) <= 1e-8f) {
        manifest_normalization_scale = 1.0f;
    }
    for (const std::string& object : objects_with_key(manifest, "vertex_file")) {
        PreviewBatch batch;
        parse_manifest_batch_material(batch, package_dir, object, static_cast<int>(batches.size()));
        parse_manifest_batch_identity_and_cloth(
            batch,
            package_dir,
            object,
            manifest_normalization_center,
            manifest_normalization_scale,
            stats);
        record_manifest_batch_stats(batch, object, stats);
        if (batch.vertex_count > 0 && !batch.vertex_file.empty()) {
            batches.push_back(batch);
        }
    }
    if (!parse_manifest_metadata(manifest, batches, stats)) {
        return batches;
    }
    const std::string placement_frame = json_object_field(manifest, "placement_frame");
    if (!placement_frame.empty()) {
        stats.placement_frame_kind = json_string_field(placement_frame, "kind");
        stats.grid_mode = lower_copy(json_string_field(placement_frame, "grid_mode"));
        const float placement_grid_y = json_float_field(placement_frame, "grid_y", 0.0f);
        if (std::isfinite(placement_grid_y)) {
            stats.grid_y = placement_grid_y;
            stats.placement_grid_valid = true;
        }
        stats.reference_tint_mode = lower_copy(json_string_field(placement_frame, "reference_tint_mode"));
        if (stats.reference_tint_mode.empty() && lower_copy(json_string_field(placement_frame, "material_parity")) == "archive_preview") {
            stats.reference_tint_mode = "overlay_only";
        }
    }
    stats.reference_material_policy = lower_copy(json_string_field(manifest, "reference_material_policy"));
    if (stats.reference_tint_mode.empty() && stats.reference_material_policy == "preserve") {
        stats.reference_tint_mode = "overlay_only";
    }
    const std::string physics_overlays = json_object_field(manifest, "physics_overlays");
    if (!physics_overlays.empty()) {
        stats.physics_overlay_enabled = json_bool_field(physics_overlays, "enabled", false);
        stats.physics_overlay_cloth = json_bool_field(physics_overlays, "cloth", false);
        stats.physics_shape_count = std::max(0, json_int_field(physics_overlays, "physics_shape_count", 0));
        stats.physics_anchor_count = std::max(0, json_int_field(physics_overlays, "anchor_count", 0));
        stats.physics_constraint_count = std::max(0, json_int_field(physics_overlays, "constraint_count", 0));
    }
    const std::string cloth_runtime_debug = json_object_field(manifest, "cloth_runtime_debug");
    if (!cloth_runtime_debug.empty()) {
        stats.cloth_runtime_debug_enabled = json_bool_field(cloth_runtime_debug, "enabled", false);
    }
    const std::string skeleton_overlay = json_object_field(manifest, "skeleton_overlay");
    if (!skeleton_overlay.empty()) {
        stats.skeleton_bone_count = std::max(0, json_int_field(skeleton_overlay, "bone_count", 0));
        stats.skeleton_overlay_enabled = json_bool_field(skeleton_overlay, "enabled", false) && stats.skeleton_bone_count > 0;
        stats.skeleton_pose_enabled = json_bool_field(skeleton_overlay, "pose_enabled", false);
        stats.skeleton_selected_bone_index = json_int_field(skeleton_overlay, "selected_bone_index", -1);
        stats.skeleton_posed_bone_count = std::max(0, json_int_field(skeleton_overlay, "posed_bone_count", 0));
    }
    stats.editable_value_group_count = static_cast<int>(json_object_array_field(manifest, "editable_value_groups").size());
    return batches;
}
