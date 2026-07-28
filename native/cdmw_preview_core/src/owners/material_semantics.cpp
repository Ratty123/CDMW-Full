
static std::string texture_role_from_name(const std::string& raw_name) {
    const std::string name = lower_copy(raw_name);
    if (name.find("_emi.dds") != std::string::npos || name.find("emissive") != std::string::npos || name.find("glow") != std::string::npos || name.find("illum") != std::string::npos) return "emissive";
    if (name.find("_flow") != std::string::npos || name.find("flow") != std::string::npos) return "flow";
    if (name.find("_f.dds") != std::string::npos || name.find("_flowmap.dds") != std::string::npos) return "flow";
    if (name.find("_dr.dds") != std::string::npos || name.find("_direction") != std::string::npos) return "flow";
    if (name.find("_n.dds") != std::string::npos || name.find("normal") != std::string::npos) return "normal";
    if (name.find("_disp.dds") != std::string::npos || name.find("height") != std::string::npos || name.find("displacement") != std::string::npos) return "height";
    if (name.find("_ao.dds") != std::string::npos || name.find("ambientocclusion") != std::string::npos || name.find("occlusion") != std::string::npos) return "occlusion";
    if (name.find("roughness") != std::string::npos || name.find("_rgh") != std::string::npos) return "roughness";
    if (name.find("metallic") != std::string::npos || name.find("metalness") != std::string::npos) return "metalness";
    if (name.find("gloss") != std::string::npos || name.find("smoothness") != std::string::npos) return "specular";
    if (name.find("_sp.dds") != std::string::npos || name.find("specular") != std::string::npos) return "specular";
    if (name.find("_ma.dds") != std::string::npos || name.find("_m.dds") != std::string::npos || name.find("material") != std::string::npos) return "material";
    if (name.find("_mg.dds") != std::string::npos || name.find("detail") != std::string::npos || name.find("grime") != std::string::npos || name.find("mask") != std::string::npos) return "detail";
    if (name.find("_o.dds") != std::string::npos || name.find("base") != std::string::npos || name.find("diffuse") != std::string::npos || name.find("albedo") != std::string::npos || name.find("texturelayer") != std::string::npos) return "base";
    return "base";
}

static bool direct_emissive_texture_or_shader_evidence(
    const std::string& texture_path,
    const std::string& texture_name,
    const std::string& shader_family
) {
    const std::string texture_text = lower_copy(texture_path + " " + texture_name);
    if (
        texture_text.find("_emi.dds") != std::string::npos
        || texture_text.find("emissive") != std::string::npos
        || texture_text.find("glow") != std::string::npos
        || texture_text.find("illum") != std::string::npos
    ) {
        return true;
    }
    const std::string shader_text = lower_copy(shader_family);
    return shader_text.find("emissive") != std::string::npos
        || shader_text.find("glow") != std::string::npos
        || shader_text.find("illum") != std::string::npos;
}

static bool role_is_technical_for_base(const std::string& role) {
    return role == "normal" || role == "height" || role == "material" || role == "detail" || role == "specular" || role == "flow" || role == "opacity" || role == "emissive";
}

static std::string normalize_visible_texture_mode(const std::string& mode) {
    const std::string lower = lower_copy(mode);
    if (lower == "mesh_base_first" || lower == "layer_aware_visible" || lower == "sidecar_visible_first") {
        return lower;
    }
    return "mesh_base_first";
}

static bool path_has_suffix_stem(const std::string& raw_path, const std::string& suffix) {
    const std::string stem = lower_copy(stem_from_path(raw_path));
    return stem.size() >= suffix.size() && stem.compare(stem.size() - suffix.size(), suffix.size(), suffix) == 0;
}

static bool low_authority_base_path(const std::string& raw_path) {
    const std::string stem = lower_copy(stem_from_path(raw_path));
    if (stem.empty()) return false;
    if (stem.find("nonetexture") != std::string::npos || stem.find("nulltexture") != std::string::npos || stem.find("dummytexture") != std::string::npos) return true;
    if (stem.find("common_default") != std::string::npos && stem.find("overlay") != std::string::npos) return true;
    if (stem == "cd_common_default_overlay" || stem == "cd_common_default_overlay_old") return true;
    if (path_has_suffix_stem(raw_path, "_o") || stem.find("_overlay") != std::string::npos) return true;
    return false;
}

static bool base_binding_is_low_authority_overlay(const TextureBinding* binding) {
    return binding != nullptr
        && (low_authority_base_path(binding->archive_path) || low_authority_base_path(binding->texture_name));
}

static bool placeholder_visible_base_path(const std::string& raw_path) {
    const std::string stem = lower_copy(stem_from_path(raw_path));
    if (stem.empty()) return false;
    if (stem.find("nonetexture") != std::string::npos || stem.find("nulltexture") != std::string::npos || stem.find("dummytexture") != std::string::npos) return true;
    if (stem == "cd_common_default_overlay" || stem == "cd_common_default_overlay_old") return true;
    if (stem.find("common_default") != std::string::npos && stem.find("overlay") != std::string::npos) return true;
    // cd_temp_* is unfinished authoring left in the shipped archive. The layer
    // mask guard below already rejects it; a visible base has at least as much
    // reason to. cd_phm_00_bag_0068 showed cd_temp_black.dds as the albedo of
    // ten of its parts.
    if (stem == "cd_temp" || stem.rfind("cd_temp_", 0) == 0) return true;
    return false;
}

static bool placeholder_layer_mask_path(const std::string& raw_path) {
    const std::string stem = lower_copy(stem_from_path(raw_path));
    if (stem.empty()) return false;
    if (stem.find("nonetexture") != std::string::npos || stem.find("nulltexture") != std::string::npos || stem.find("dummytexture") != std::string::npos) return true;
    if (stem.find("common_default") != std::string::npos) return true;
    if (stem == "cd_temp" || stem.rfind("cd_temp_", 0) == 0) return true;
    return false;
}

static bool technical_for_visible_base(const std::string& parameter_name, const std::string& raw_path, const std::string& role) {
    const std::string hint = lower_copy(parameter_name);
    const std::string path = lower_copy(raw_path);
    const std::string compact_hint = std::regex_replace(hint, std::regex("[^a-z0-9]+"), "");
    const std::string compact_path = std::regex_replace(path, std::regex("[^a-z0-9]+"), "");
    if (role_is_technical_for_base(role)) return true;
    if (compact_hint.find("ssdm") != std::string::npos || compact_hint.find("direction") != std::string::npos) return true;
    if (compact_hint.find("normal") != std::string::npos || compact_hint.find("height") != std::string::npos) return true;
    if (compact_hint.find("displacement") != std::string::npos || compact_hint.find("material") != std::string::npos) return true;
    if (compact_hint.find("roughness") != std::string::npos || compact_hint.find("metallic") != std::string::npos) return true;
    if (compact_path.find("roughness") != std::string::npos || compact_path.find("metallic") != std::string::npos || compact_path.find("metalness") != std::string::npos) return true;
    if (compact_path.find("ambientocclusion") != std::string::npos || compact_path.find("occlusion") != std::string::npos) return true;
    if (compact_hint.find("occlusion") != std::string::npos || compact_hint.find("opacity") != std::string::npos) return true;
    if (compact_hint.find("specular") != std::string::npos || compact_hint.find("orm") != std::string::npos) return true;
    if (compact_hint == "colorblendingmasktexture" || compact_hint == "detailmasktexture") return true;
    if (compact_hint.find("mask") != std::string::npos && compact_hint.find("diffuse") == std::string::npos && compact_hint.find("albedo") == std::string::npos && compact_hint.find("color") == std::string::npos) return true;
    if (path_has_suffix_stem(raw_path, "_n") || path_has_suffix_stem(raw_path, "_disp") || path_has_suffix_stem(raw_path, "_ma")) return true;
    if (path_has_suffix_stem(raw_path, "_mg") || path_has_suffix_stem(raw_path, "_sp") || path_has_suffix_stem(raw_path, "_m")) return true;
    if (path_has_suffix_stem(raw_path, "_dr")) return true;
    // A decal or blend input paints a local mark -- damage, scorch, an emblem --
    // over a surface that already has a colour, and its alpha is the mark's own
    // shape. Promoted to the visible base it paints the whole part with the decal
    // sheet, including the rectangle around the mark. `_detailDiffuseBlend`
    // pointing at cd_texturelayer_100_0044_dec.dds became the albedo of
    // cd_phm_02_sword_0036_in this way, over the grime layers that hold its real
    // colour. `_colorBlending*` is a layer selector handled above, not a decal.
    if (compact_hint.find("blend") != std::string::npos
        && compact_hint.find("colorblending") == std::string::npos) return true;
    if (path_has_suffix_stem(raw_path, "_dec")) return true;
    // An opacity mask carries coverage, not colour. `_overlayColorTexture` on the
    // shared wrinkle material points at cd_common_00_ub_0001_wrinkle0_opacity.dds,
    // and the parameter name alone does not say so.
    if (path_has_suffix_stem(raw_path, "_opacity")) return true;
    // `_tornPatternTexture` carries the shape of a tear, not a colour. Every one
    // of its 13 bindings across 4,665 sampled assets points at
    // cd_texturelayer_endpattern_0001_tp.dds, a shared library pattern; where it
    // won the visible base the garment rendered as neon green and magenta
    // stripes, which is that pattern sampled as albedo.
    if (compact_hint.find("tornpattern") != std::string::npos) return true;
    if (path_has_suffix_stem(raw_path, "_tp")) return true;
    // Placeholders and unfinished authoring: the visible-base guard knew about
    // these but only the layer paths consulted it, so the primary selector let a
    // default overlay or a cd_temp_* texture become a part's albedo.
    if (placeholder_visible_base_path(raw_path)) return true;
    // The shared damage library paints wear over a surface that already has a
    // colour. Same contract as a decal, without the `_dec` suffix that catches
    // the rest of them.
    const std::string stem = lower_copy(stem_from_path(raw_path));
    if (stem.rfind("cd_texturelayer_damaged", 0) == 0) return true;
    // Screen-space and condition FX noise is a modulation source, never albedo.
    if (compact_hint.find("noise") != std::string::npos) return true;
    if (stem.rfind("cdfx_", 0) == 0 && stem.find("noise") != std::string::npos) return true;
    if (path_has_suffix_stem(raw_path, "_orm") || path_has_suffix_stem(raw_path, "_rma") || path_has_suffix_stem(raw_path, "_mra")) return true;
    return false;
}

static bool parameter_is_authoritative_visible_base(const std::string& parameter_name) {
    const std::string hint = std::regex_replace(lower_copy(parameter_name), std::regex("[^a-z0-9]+"), "");
    if (
        hint.find("grime") != std::string::npos
        || hint.find("detail") != std::string::npos
        || hint.find("damage") != std::string::npos
        || hint.find("dye") != std::string::npos
        || hint.find("layer") != std::string::npos
    ) {
        return false;
    }
    return hint == "basecolortexture"
        || hint == "diffusetexture"
        || hint == "albedotexture"
        || hint == "overlaycolortexture"
        || hint.find("basecolor") != std::string::npos
        || (hint.find("diffuse") != std::string::npos && hint.find("mask") == std::string::npos)
        || (hint.find("albedo") != std::string::npos && hint.find("mask") == std::string::npos);
}

static std::string visible_class_for_binding(const std::string& parameter_name, const std::string& raw_path, const std::string& role) {
    if (technical_for_visible_base(parameter_name, raw_path, role)) return "technical";
    const std::string hint = std::regex_replace(lower_copy(parameter_name), std::regex("[^a-z0-9]+"), "");
    if (hint.find("overlaycolor") != std::string::npos || low_authority_base_path(raw_path)) {
        return "visible_generic";
    }
    if (hint.find("grime") != std::string::npos || hint.find("detail") != std::string::npos || hint.find("layer") != std::string::npos || hint.find("blend") != std::string::npos || hint.find("decal") != std::string::npos) {
        return "layer_visible";
    }
    if (hint.find("basecolor") != std::string::npos || hint.find("basecolour") != std::string::npos || hint.find("albedo") != std::string::npos || hint.find("diffuse") != std::string::npos || hint.find("colortexture") != std::string::npos || hint.find("base") != std::string::npos) {
        return "primary_visible";
    }
    if (hint.find("color") != std::string::npos || hint.find("colour") != std::string::npos || hint.find("overlay") != std::string::npos || hint.find("tint") != std::string::npos || hint.find("emissive") != std::string::npos) {
        return "visible_generic";
    }
    return "visible_generic";
}

static bool visible_class_allowed_for_mode(const std::string& mode, const std::string& visible_class) {
    if (visible_class == "technical") return false;
    const std::string normalized = normalize_visible_texture_mode(mode);
    if (normalized == "mesh_base_first") return visible_class == "primary_visible" || visible_class == "layer_visible";
    return visible_class == "primary_visible" || visible_class == "visible_generic" || visible_class == "layer_visible";
}

static int visible_class_priority(const std::string& visible_class) {
    if (visible_class == "primary_visible") return 3;
    if (visible_class == "layer_visible") return 2;
    if (visible_class == "visible_generic") return 1;
    return 0;
}

static std::string package_label_for_ref(const ArchiveEntryRef& ref) {
    if (ref.pamt_path.empty()) return "";
    std::string parent = ref.pamt_path.parent_path().filename().string();
    std::string name = ref.pamt_path.filename().string();
    return parent.empty() ? name : (parent + "/" + name);
}

static void add_asset_family_row(NativePackage& package, NativeAssetFamilyRow row) {
    if (row.path.empty() && row.display_name.empty()) return;
    if (row.display_name.empty()) row.display_name = basename_from_path(row.path);
    if (row.reason.empty()) row.reason = "Recovered by native preview-core.";
    if (row.package_label.empty()) {
        row.package_label = "";
    }
    const std::string key = lower_copy(row.group + "|" + row.role + "|" + row.path + "|" + row.display_name + "|" + row.semantic_hint);
    for (const NativeAssetFamilyRow& existing : package.asset_family_rows) {
        const std::string existing_key = lower_copy(existing.group + "|" + existing.role + "|" + existing.path + "|" + existing.display_name + "|" + existing.semantic_hint);
        if (existing_key == key) return;
    }
    package.asset_family_rows.push_back(std::move(row));
}

static std::string semantic_subtype_for_role(const std::string& role) {
    if (role == "emissive") return "emissive";
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "detail") return "detail_mask";
    if (role == "material") return "material_mask";
    if (role == "flow") return "flow";
    if (role == "opacity") return "opacity";
    return "base_color";
}

static std::vector<std::string> extract_dds_tokens(const std::string& text) {
    std::vector<std::string> tokens;
    std::set<std::string> seen;
    const std::regex pattern("([A-Za-z0-9_./\\\\-]+\\.dds)", std::regex_constants::icase);
    auto begin = std::sregex_iterator(text.begin(), text.end(), pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        std::string token = (*it)[1].str();
        std::replace(token.begin(), token.end(), '\\', '/');
        const std::string key = lower_copy(basename_from_path(token));
        if (!key.empty() && seen.insert(key).second) {
            tokens.push_back(token);
        }
    }
    return tokens;
}

struct SidecarTextureRef {
    std::string path;
    std::string parameter_name;
    std::string material_name;
    std::string shader_family;
    int material_wrapper_index = -1;
    std::vector<MaterialParameterRecord> material_parameters;
};

static std::string xml_attr_value(const std::string& text, std::initializer_list<const char*> names);
static std::map<std::string, std::string> xml_attribute_map(const std::string& tag_text);
static std::string xml_attr_value_from_map(const std::map<std::string, std::string>& attrs, std::initializer_list<const char*> names);
static std::vector<std::string> collect_xml_tag_blocks(const std::string& text, const std::string& tag_name);
static std::string shader_rule_for_family(const std::string& family);

static std::string normalized_key(std::string value) {
    std::string out;
    out.reserve(value.size());
    for (char ch : value) {
        if (std::isalnum(static_cast<unsigned char>(ch))) {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(ch))));
        }
    }
    return out;
}

static std::array<float, 4> byte4_channels(const std::string& raw_value) {
    std::array<float, 4> channels{0.0f, 0.0f, 0.0f, 0.0f};
    if (raw_value.empty()) return channels;
    try {
        unsigned long value = std::stoul(raw_value);
        value = std::min<unsigned long>(value, 0xFFFFFFFFul);
        for (int index = 0; index < 4; ++index) {
            channels[static_cast<size_t>(index)] = static_cast<float>((value >> (8 * index)) & 0xFFu) / 255.0f;
        }
    } catch (...) {
    }
    return channels;
}

static float numeric_parameter_value(const std::string& raw_value, bool* ok = nullptr) {
    if (ok) *ok = false;
    if (raw_value.empty()) return 0.0f;
    try {
        size_t consumed = 0;
        float value = std::stof(raw_value, &consumed);
        if (consumed == 0) return 0.0f;
        if (ok) *ok = true;
        return value;
    } catch (...) {
        return 0.0f;
    }
}

static std::array<float, 4> color_parameter_value(const std::string& raw_value) {
    std::array<float, 4> color{1.0f, 1.0f, 1.0f, 1.0f};
    std::string text = raw_value;
    if (!text.empty() && text.front() == '#') text.erase(text.begin());
    if (text.size() != 6 && text.size() != 8) return color;
    try {
        const int r = std::stoi(text.substr(0, 2), nullptr, 16);
        const int g = std::stoi(text.substr(2, 2), nullptr, 16);
        const int b = std::stoi(text.substr(4, 2), nullptr, 16);
        const int a = text.size() >= 8 ? std::stoi(text.substr(6, 2), nullptr, 16) : 255;
        color = {r / 255.0f, g / 255.0f, b / 255.0f, a / 255.0f};
    } catch (...) {
    }
    return color;
}

static std::vector<MaterialParameterRecord> extract_material_parameters(const std::string& scope_text) {
    std::vector<MaterialParameterRecord> records;
    const std::vector<std::pair<std::string, std::string>> parameter_tags = {
        {"MaterialParameterFloat", "float"},
        {"MaterialParameterColor", "color"},
        {"MaterialParameterByte4", "byte4"},
        {"MaterialParameterBitFlag32", "bitflag32"},
        {"MaterialParameterUint", "uint"},
        {"MaterialParameterUInt", "uint"},
        {"MaterialParameterInt", "int"},
        {"MaterialParameterBool", "bool"},
    };
    for (const auto& [tag_name, kind] : parameter_tags) {
        for (const std::string& tag : collect_xml_tag_blocks(scope_text, tag_name)) {
            const auto attrs = xml_attribute_map(tag);
            MaterialParameterRecord record;
            record.kind = kind;
            record.name = xml_attr_value_from_map(attrs, {"_name", "StringItemID", "Name"});
            record.value = xml_attr_value_from_map(attrs, {"_value", "Value", "DefaultValue"});
            if (record.name.empty()) continue;
            bool has_numeric = false;
            record.numeric_value = numeric_parameter_value(record.value, &has_numeric);
            record.has_numeric = has_numeric;
            records.push_back(record);
        }
    }
    return records;
}

static const MaterialParameterRecord* find_material_parameter(
    const std::vector<MaterialParameterRecord>& parameters,
    std::initializer_list<const char*> names
) {
    for (const MaterialParameterRecord& parameter : parameters) {
        const std::string key = normalized_key(parameter.name);
        for (const char* name : names) {
            const std::string wanted = normalized_key(name);
            if (!wanted.empty() && key.find(wanted) != std::string::npos) return &parameter;
        }
    }
    return nullptr;
}

static bool material_parameters_enable_flag(
    const std::vector<MaterialParameterRecord>& parameters,
    std::initializer_list<const char*> names
) {
    const MaterialParameterRecord* parameter = find_material_parameter(parameters, names);
    if (parameter == nullptr) return false;
    std::string value = lower_copy(parameter->value);
    value.erase(std::remove_if(value.begin(), value.end(), [](unsigned char ch) {
        return std::isspace(ch) != 0;
    }), value.end());
    if (value.empty()) return true;
    if (value == "true" || value == "yes" || value == "on") return true;
    if (value == "false" || value == "no" || value == "off") return false;
    if (parameter->has_numeric) return std::abs(parameter->numeric_value) > 0.0001f;
    return value != "0";
}

static std::array<float, 4> byte4_parameter_channels(
    const std::vector<MaterialParameterRecord>& parameters,
    std::initializer_list<const char*> names
) {
    const MaterialParameterRecord* parameter = find_material_parameter(parameters, names);
    if (parameter == nullptr) return {0.0f, 0.0f, 0.0f, 0.0f};
    return byte4_channels(parameter->value);
}

static float scalar_parameter_hint(
    const std::vector<MaterialParameterRecord>& parameters,
    std::initializer_list<const char*> names,
    float fallback = 0.0f
) {
    const MaterialParameterRecord* parameter = find_material_parameter(parameters, names);
    if (parameter == nullptr) return fallback;
    if (parameter->kind == "byte4") {
        const auto channels = byte4_channels(parameter->value);
        return std::max({channels[0], channels[1], channels[2], channels[3], fallback});
    }
    return parameter->has_numeric ? parameter->numeric_value : fallback;
}

static std::string joined_parameter_names(const std::vector<MaterialParameterRecord>& parameters, size_t limit = 16) {
    std::ostringstream out;
    size_t count = 0;
    for (const MaterialParameterRecord& parameter : parameters) {
        if (parameter.name.empty()) continue;
        if (count++) out << ",";
        out << parameter.name;
        if (count >= limit) break;
    }
    return out.str();
}

static std::string extract_shader_family_hint(const std::string& text) {
    const std::regex material_name_pattern("(?:^|[\\s<])(?:_materialName|MaterialName|TechniqueName)=\"([^\"]+)\"", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(text, match, material_name_pattern)) return match[1].str();
    const std::regex pattern(
        "(SkinnedMesh(?:Skin(?:Wrinkle)?|Standard(?:_Ver[0-9]+)?|Cloth(?:_Ver[0-9]+)?|Hair|Fur(?:_Ver[0-9]+)?|AnimalHair)|MultiTextured|Standard)",
        std::regex_constants::icase
    );
    if (std::regex_search(text, match, pattern)) return match[1].str();
    return "";
}

static std::string xml_attr_value(const std::string& text, std::initializer_list<const char*> names) {
    for (const char* raw_name : names) {
        const std::string name(raw_name);
        const std::regex pattern("(?:^|\\s)" + name + "=\"([^\"]*)\"", std::regex_constants::icase);
        std::smatch match;
        if (std::regex_search(text, match, pattern)) return match[1].str();
    }
    return "";
}

static size_t xml_open_tag_end(const std::string& text, size_t start) {
    bool in_quote = false;
    for (size_t index = start; index < text.size(); ++index) {
        const char ch = text[index];
        if (ch == '"') in_quote = !in_quote;
        if (ch == '>' && !in_quote) return index;
    }
    return std::string::npos;
}

static bool xml_tag_name_boundary(char ch) {
    return std::isspace(static_cast<unsigned char>(ch)) || ch == '>' || ch == '/';
}

static std::map<std::string, std::string> xml_attribute_map(const std::string& tag_text) {
    std::map<std::string, std::string> attrs;
    const size_t open = tag_text.find('<');
    const size_t end = xml_open_tag_end(tag_text, open == std::string::npos ? 0 : open);
    if (open == std::string::npos || end == std::string::npos || end <= open) return attrs;
    size_t index = open + 1;
    while (index < end && !std::isspace(static_cast<unsigned char>(tag_text[index])) && tag_text[index] != '>' && tag_text[index] != '/') {
        ++index;
    }
    while (index < end) {
        while (index < end && std::isspace(static_cast<unsigned char>(tag_text[index]))) ++index;
        if (index >= end || tag_text[index] == '/') break;
        const size_t key_start = index;
        while (index < end && tag_text[index] != '=' && !std::isspace(static_cast<unsigned char>(tag_text[index]))) ++index;
        std::string key = tag_text.substr(key_start, index - key_start);
        while (index < end && std::isspace(static_cast<unsigned char>(tag_text[index]))) ++index;
        if (index >= end || tag_text[index] != '=') {
            attrs[lower_copy(key)] = "";
            continue;
        }
        ++index;
        while (index < end && std::isspace(static_cast<unsigned char>(tag_text[index]))) ++index;
        std::string value;
        if (index < end && tag_text[index] == '"') {
            ++index;
            const size_t value_start = index;
            while (index < end && tag_text[index] != '"') ++index;
            value = tag_text.substr(value_start, index - value_start);
            if (index < end && tag_text[index] == '"') ++index;
        } else {
            const size_t value_start = index;
            while (index < end && !std::isspace(static_cast<unsigned char>(tag_text[index])) && tag_text[index] != '>') ++index;
            value = tag_text.substr(value_start, index - value_start);
        }
        if (!key.empty()) attrs[lower_copy(key)] = value;
    }
    return attrs;
}

static std::string xml_attr_value_from_map(const std::map<std::string, std::string>& attrs, std::initializer_list<const char*> names) {
    for (const char* raw_name : names) {
        auto found = attrs.find(lower_copy(raw_name));
        if (found != attrs.end()) return found->second;
    }
    return "";
}

static std::vector<std::string> collect_xml_tag_blocks(const std::string& text, const std::string& tag_name) {
    std::vector<std::string> blocks;
    if (text.empty() || tag_name.empty()) return blocks;
    const std::string lowered = lower_copy(text);
    const std::string open_token = "<" + lower_copy(tag_name);
    const std::string close_token = "</" + lower_copy(tag_name) + ">";
    size_t search = 0;
    while (true) {
        const size_t open = lowered.find(open_token, search);
        if (open == std::string::npos) break;
        const size_t name_end = open + open_token.size();
        if (name_end < lowered.size() && !xml_tag_name_boundary(lowered[name_end])) {
            search = name_end;
            continue;
        }
        const size_t open_end = xml_open_tag_end(text, open);
        if (open_end == std::string::npos) break;
        size_t block_end = open_end + 1;
        size_t cursor = open_end;
        while (cursor > open && std::isspace(static_cast<unsigned char>(text[cursor - 1]))) --cursor;
        const bool self_closing = cursor > open && text[cursor - 1] == '/';
        if (!self_closing) {
            const size_t close = lowered.find(close_token, open_end + 1);
            if (close == std::string::npos) {
                search = open_end + 1;
                continue;
            }
            block_end = close + close_token.size();
        }
        blocks.push_back(text.substr(open, block_end - open));
        search = block_end;
    }
    return blocks;
}

static std::vector<std::string> collect_xml_open_tags(const std::string& text) {
    std::vector<std::string> tags;
    if (text.empty()) return tags;
    const std::regex pattern("<[^!?/][^>]*>");
    auto begin = std::sregex_iterator(text.begin(), text.end(), pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        tags.push_back(it->str());
    }
    return tags;
}

static std::string native_joined_lower(std::initializer_list<std::string> values) {
    std::string joined;
    for (const std::string& value : values) {
        if (!joined.empty()) joined.push_back(' ');
        joined += lower_copy(value);
    }
    return joined;
}

static bool native_cloth_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("cloth") != std::string::npos
        || text.find("cloak") != std::string::npos
        || text.find("cape") != std::string::npos
        || text.find("skirt") != std::string::npos
        || text.find("dress") != std::string::npos
        || text.find("mantle") != std::string::npos
        || text.find("robe") != std::string::npos
        || text.find("flap") != std::string::npos;
}

static bool native_leather_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("leather") != std::string::npos
        || text.find("hide") != std::string::npos;
}

static bool native_hair_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("hair") != std::string::npos
        || text.find("fur") != std::string::npos;
}

static bool native_rope_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("rope") != std::string::npos
        || text.find("cord") != std::string::npos
        || text.find("string") != std::string::npos
        || text.find("thread") != std::string::npos
        || text.find("tassel") != std::string::npos
        || text.find("strap") != std::string::npos
        || text.find("belt") != std::string::npos;
}

static bool native_spline_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("spline") != std::string::npos
        || text.find("chain") != std::string::npos
        || text.find("whip") != std::string::npos
        || text.find("tail") != std::string::npos;
}

static bool native_body_soft_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("breast") != std::string::npos
        || text.find("belly") != std::string::npos
        || text.find("body_soft") != std::string::npos
        || text.find("softbody") != std::string::npos
        || text.find("soft_body") != std::string::npos
        || text.find("jiggle") != std::string::npos;
}

static bool native_rigid_pbd_token_match(const std::string& value) {
    const std::string text = lower_copy(value);
    return text.find("weapon") != std::string::npos
        || text.find("blade") != std::string::npos
        || text.find("guard") != std::string::npos
        || text.find("handle") != std::string::npos
        || text.find("hilt") != std::string::npos
        || text.find("sword") != std::string::npos
        || text.find("metal") != std::string::npos
        || text.find("steel") != std::string::npos
        || text.find("iron") != std::string::npos
        || text.find("rigid") != std::string::npos;
}

static bool native_soft_pbd_kind(const std::string& kind_value) {
    const std::string kind = lower_copy(kind_value.empty() ? "unknown" : kind_value);
    return kind == "cloth"
        || kind == "leather"
        || kind == "hair"
        || kind == "rope"
        || kind == "spline"
        || kind == "body_soft"
        || kind == "unknown";
}

static bool native_soft_pbd_token_match(const std::string& value) {
    return native_cloth_token_match(value)
        || native_leather_token_match(value)
        || native_hair_token_match(value)
        || native_rope_token_match(value)
        || native_spline_token_match(value)
        || native_body_soft_token_match(value);
}

static bool native_pbd_hint_is_soft_physics(const NativePbdSidecarHint& hint) {
    const std::string kind = lower_copy(hint.simulation_kind);
    const std::string context = hint.simulation_material_name + " " +
        hint.material_name + " " +
        hint.submesh_name + " " +
        hint.parameter_name;
    if (!native_soft_pbd_kind(kind)) return false;
    if (kind == "spline" && native_rigid_pbd_token_match(context) && !native_rope_token_match(context)) return false;
    if (native_rigid_pbd_token_match(context) && !native_soft_pbd_token_match(context)) return false;
    return true;
}

static bool native_pbd_hint_is_cloth(const NativePbdSidecarHint& hint) {
    return lower_copy(hint.simulation_kind) == "cloth" && native_pbd_hint_is_soft_physics(hint);
}

static bool native_pbd_hints_have_cloth(const std::vector<NativePbdSidecarHint>& hints) {
    for (const NativePbdSidecarHint& hint : hints) {
        if (native_pbd_hint_is_cloth(hint)) return true;
    }
    return false;
}

static bool native_pbd_hints_have_soft_physics(const std::vector<NativePbdSidecarHint>& hints) {
    for (const NativePbdSidecarHint& hint : hints) {
        if (native_pbd_hint_is_soft_physics(hint)) return true;
    }
    return false;
}

static std::string native_pbd_simulation_kind(std::initializer_list<std::string> values) {
    const std::string joined = native_joined_lower(values);
    if (native_hair_token_match(joined)) {
        return "hair";
    }
    if (native_body_soft_token_match(joined)) {
        return "body_soft";
    }
    if (native_leather_token_match(joined)) {
        return "leather";
    }
    if (native_rope_token_match(joined)) {
        return "rope";
    }
    if (native_cloth_token_match(joined)) {
        return "cloth";
    }
    if (native_spline_token_match(joined)) {
        return "spline";
    }
    return "unknown";
}
