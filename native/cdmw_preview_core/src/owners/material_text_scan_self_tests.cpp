// The linear sidecar scans against the regular expressions they stand in for.

static std::vector<std::string> reference_dds_tokens(const std::string& text) {
    std::vector<std::string> tokens;
    std::set<std::string> seen;
    static const std::regex pattern("([A-Za-z0-9_./\\\\-]+\\.dds)", std::regex_constants::icase);
    for (auto it = std::sregex_iterator(text.begin(), text.end(), pattern); it != std::sregex_iterator(); ++it) {
        std::string token = (*it)[1].str();
        std::replace(token.begin(), token.end(), '\\', '/');
        const std::string key = lower_copy(basename_from_path(token));
        if (!key.empty() && seen.insert(key).second) tokens.push_back(token);
    }
    return tokens;
}

static std::string reference_shader_family_hint(const std::string& text) {
    static const std::regex material_name_pattern(
        "(?:^|[\\s<])(?:_materialName|MaterialName|TechniqueName)=\"([^\"]+)\"", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(text, match, material_name_pattern)) return match[1].str();
    static const std::regex pattern(
        "(SkinnedMesh(?:Skin(?:Wrinkle)?|Standard(?:_Ver[0-9]+)?|Cloth(?:_Ver[0-9]+)?|Hair|Fur(?:_Ver[0-9]+)?|AnimalHair)|MultiTextured|Standard)",
        std::regex_constants::icase);
    if (std::regex_search(text, match, pattern)) return match[1].str();
    return "";
}

static int reference_regex_count(const std::string& text, const std::regex& pattern) {
    return static_cast<int>(std::distance(std::sregex_iterator(text.begin(), text.end(), pattern), std::sregex_iterator()));
}

static SidecarParameterSummary reference_sidecar_parameter_summary(const std::string& text) {
    static const std::regex texture("MaterialParameterTexture", std::regex_constants::icase);
    static const std::regex number("MaterialParameterFloat|<FloatParameter|_float", std::regex_constants::icase);
    static const std::regex color("MaterialParameterColor|ColorParameter|Tint|_color", std::regex_constants::icase);
    static const std::regex byte4("MaterialParameterByte4|Byte4", std::regex_constants::icase);
    static const std::regex flags("BitFlag|MaterialBit|_flag", std::regex_constants::icase);
    static const std::regex linked_mesh_pattern(
        "([A-Za-z0-9_./\\\\-]+\\.(?:pac|pam|pamlod))", std::regex_constants::icase);
    SidecarParameterSummary summary;
    summary.texture_params = reference_regex_count(text, texture);
    summary.float_params = reference_regex_count(text, number);
    summary.color_params = reference_regex_count(text, color);
    summary.byte4_params = reference_regex_count(text, byte4);
    summary.bit_flags = reference_regex_count(text, flags);
    std::smatch match;
    if (std::regex_search(text, match, linked_mesh_pattern)) {
        summary.linked_mesh_path = match[1].str();
        std::replace(summary.linked_mesh_path.begin(), summary.linked_mesh_path.end(), '\\', '/');
    }
    return summary;
}

static std::vector<std::string> reference_xml_open_tags(const std::string& text) {
    std::vector<std::string> tags;
    static const std::regex pattern("<[^!?/][^>]*>");
    for (auto it = std::sregex_iterator(text.begin(), text.end(), pattern); it != std::sregex_iterator(); ++it) {
        tags.push_back(it->str());
    }
    return tags;
}

// collect_xml_tag_blocks as it was, searching a lower-cased copy of the text.
static std::vector<std::string> reference_xml_tag_blocks(const std::string& text, const std::string& tag_name) {
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

static void require_same_sidecar_scan(const std::string& text) {
    const SidecarParameterSummary summary = summarize_sidecar_parameters(text);
    const SidecarParameterSummary reference = reference_sidecar_parameter_summary(text);
    bool same = extract_dds_tokens(text) == reference_dds_tokens(text)
        && extract_shader_family_hint(text) == reference_shader_family_hint(text)
        && collect_xml_open_tags(text) == reference_xml_open_tags(text)
        && summary.texture_params == reference.texture_params
        && summary.float_params == reference.float_params
        && summary.color_params == reference.color_params
        && summary.byte4_params == reference.byte4_params
        && summary.bit_flags == reference.bit_flags
        && summary.linked_mesh_path == reference.linked_mesh_path;
    for (const char* tag_name : {"ModelProperty", "MaterialParameterTexture", "Material"}) {
        same = same && collect_xml_tag_blocks(text, tag_name) == reference_xml_tag_blocks(text, tag_name);
    }
    if (!same) {
        std::string shown;
        for (const char ch : text.substr(0, 160)) {
            shown += (ch >= ' ' && ch < 127) ? ch : '?';
        }
        throw std::runtime_error(
            "material contract self-test failed: a sidecar text scan differs from its expression for: " + shown);
    }
}

static void run_material_text_scan_self_test() {
    for (const char* text : {
        "",
        "<ModelProperty Index=\"0\"><Material _materialName=\"Standard\">"
            "<MaterialParameterTexture _name=\"_baseColorTexture\" _value=\"object/texture/a_d.dds\"/>"
            "<MaterialParameterFloat _name=\"_tintStrength\" _value=\"1\"/></Material></ModelProperty>",
        "x_materialName=\"no\" MaterialName=\"\" <TechniqueName=\"SkinnedMeshCloth_Ver2\" tail",
        "MaterialName=\"\" <TechniqueName=\"Custom\" SkinnedMeshHair",
        "MaterialName=\"unclosed SkinnedMeshHair",
        "SkinnedMeshFur_Ver SkinnedMesh skinnedmeshanimalhair STANDARD multitextured",
        ".dds a.dds b.DDS.dds..dds c/d\\e-f.Dds.pamlod g.pac.pam h.pamlod",
        "<><<a>b<!--c--><?d?></e><f g=\"h>i\">j",
    }) {
        require_same_sidecar_scan(text);
    }
    // Text built at random from the pieces the expressions care about, including the
    // bytes a binary mesh puts between them.
    static const std::string_view pieces[] = {
        "_materialName", "MaterialName", "TechniqueName", "materialname", "=\"", "\"", "=", " ", "\n", "\t",
        "\v", "\f", "\r", "<", ">", "/", "!", "?", "\\", "-", ".", "_", "a", "Z", "0", "9", "[", "^", "`", "{",
        std::string_view("\0", 1), "\x85", "\xa0", "\xff",
        "SkinnedMesh", "skinnedmesh", "Skin", "Wrinkle", "Standard", "STANDARD", "Cloth", "Hair", "Fur",
        "AnimalHair", "_Ver", "_ver", "12", "MultiTextured", "multiTEXTURED",
        "MaterialParameterTexture", "MaterialParameterFloat", "<FloatParameter", "_float", "_FLOAT",
        "MaterialParameterColor", "ColorParameter", "Tint", "tINT", "_color", "MaterialParameterByte4", "Byte4",
        "BitFlag", "MaterialBit", "_flag", ".dds", ".DDS", ".dd", ".pac", ".pam", ".pamlod", ".PAM", "dds",
        "<ModelProperty", "</ModelProperty>", "<modelproperty ", "<MaterialParameterTexture", "/>",
        "</MaterialParameterTexture>", "<Material", "</Material>", "<Material ", "Index=\"0\"",
    };
    uint32_t state = 0x2026u;
    const auto next = [&state]() {
        state = state * 1664525u + 1013904223u;
        return state >> 8;
    };
    for (int round = 0; round < 1500; ++round) {
        std::string text;
        const uint32_t piece_count = 1 + next() % 28;
        for (uint32_t index = 0; index < piece_count; ++index) {
            text += pieces[next() % std::size(pieces)];
        }
        require_same_sidecar_scan(text);
    }
}
