static std::string json_direct_object_field(const std::string& object, const std::string& name) {
    size_t content_start = 0;
    while (content_start < object.size() && std::isspace(static_cast<unsigned char>(object[content_start]))) ++content_start;
    const int root_object_depth = content_start < object.size() && object[content_start] == '{' ? 1 : 0;
    int object_depth = 0;
    int array_depth = 0;
    bool in_string = false;
    bool escaped = false;
    for (size_t i = 0; i < object.size(); ++i) {
        const char ch = object[i];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (ch == '\\' && in_string) {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            if (!in_string && object_depth == root_object_depth && array_depth == 0) {
                const size_t key_start = i + 1;
                size_t key_end = key_start;
                bool key_escaped = false;
                for (; key_end < object.size(); ++key_end) {
                    const char key_ch = object[key_end];
                    if (key_escaped) key_escaped = false;
                    else if (key_ch == '\\') key_escaped = true;
                    else if (key_ch == '"') break;
                }
                if (key_end >= object.size()) return "";
                size_t value_start = key_end + 1;
                while (value_start < object.size() && std::isspace(static_cast<unsigned char>(object[value_start]))) ++value_start;
                if (value_start >= object.size() || object[value_start] != ':') {
                    i = key_end;
                    continue;
                }
                ++value_start;
                while (value_start < object.size() && std::isspace(static_cast<unsigned char>(object[value_start]))) ++value_start;
                if (object.compare(key_start, key_end - key_start, name) == 0) {
                    if (value_start >= object.size() || object[value_start] != '{') return "";
                    bool value_in_string = false;
                    bool value_escaped = false;
                    int value_depth = 0;
                    for (size_t value_end = value_start; value_end < object.size(); ++value_end) {
                        const char value_ch = object[value_end];
                        if (value_escaped) {
                            value_escaped = false;
                            continue;
                        }
                        if (value_ch == '\\' && value_in_string) {
                            value_escaped = true;
                            continue;
                        }
                        if (value_ch == '"') {
                            value_in_string = !value_in_string;
                            continue;
                        }
                        if (value_in_string) continue;
                        if (value_ch == '{') ++value_depth;
                        else if (value_ch == '}' && --value_depth == 0) {
                            return object.substr(value_start + 1, value_end - value_start - 1);
                        }
                    }
                    return "";
                }
                i = key_end;
                continue;
            }
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '{') ++object_depth;
        else if (ch == '}') --object_depth;
        else if (ch == '[') ++array_depth;
        else if (ch == ']') --array_depth;
    }
    return "";
}

static std::wstring dds_slot_source(const std::string& object, const std::string& slot) {
    const std::string dds_textures = json_direct_object_field(object, "dds_textures");
    if (dds_textures.empty()) return L"";
    const std::string descriptor = json_direct_object_field(dds_textures, slot);
    if (descriptor.empty()) return L"";
    if (!json_bool_field(descriptor, "available", true)) return L"";
    if (!json_bool_field(descriptor, "direct_upload_candidate", true)) return L"";
    return utf8_to_wide(json_string_field(descriptor, "source_path"));
}

static bool self_test_dds_slot_scoping() {
    const std::string batch = R"json({
        "material_inputs": {
            "base": {"source_path": "wrong_nested_base.dds", "available": true, "direct_upload_candidate": true}
        },
        "dds_textures": {
            "normal": {"source_path": "correct_normal.dds", "available": true, "direct_upload_candidate": true}
        }
    })json";
    return dds_slot_source(batch, "base").empty()
        && dds_slot_source(batch, "normal") == L"correct_normal.dds";
}
