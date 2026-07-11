static int diagnostic_mode_code(const std::string& value) {
    std::string mode = value;
    std::transform(mode.begin(), mode.end(), mode.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (mode == "lit" || mode == "final_lit" || mode == "final") return 0;
    if (mode == "base" || mode == "base_texture" || mode == "texture" || mode == "albedo" ||
        mode == "albedo_base_only" || mode == "base_only" ||
        mode == "base_direct" || mode == "base_no_tint" || mode == "base_color" || mode == "texture_probe") return 1;
    if (mode == "uv" || mode == "uv_checker" || mode == "checker") return 2;
    if (mode == "alpha" || mode == "opacity" || mode == "base_alpha") return 3;
    if (mode == "material_slot" || mode == "material_slot_id" || mode == "slot" || mode == "part_id") return 4;
    if (mode == "normal" || mode == "normals" || mode == "normal_raw") return 5;
    if (mode == "support" || mode == "support_maps" || mode == "pbr" ||
        mode == "material_raw" || mode == "height_raw" || mode == "height_calibrated" ||
        mode == "height_depth" || mode == "material_response" || mode == "metal_shine" ||
        mode == "roughness_response") return 6;
    if (mode == "layer_mask" || mode == "layer_masks" || mode == "mask" || mode == "detail_mask" ||
        mode == "masked_layer_contribution" || mode == "masked_layers") return 7;
    if (mode == "metalness" || mode == "metallic") return 8;
    if (mode == "roughness") return 9;
    if (mode == "specular_gloss" || mode == "specular_glossiness" || mode == "specular" || mode == "gloss") return 10;
    return 0;
}

static std::string wide_to_utf8(const std::wstring& text) {
    if (text.empty()) return "";
    int needed = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return "";
    std::string output(static_cast<size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed, nullptr, nullptr);
    return output;
}

static std::wstring utf8_to_wide(const std::string& text) {
    if (text.empty()) return L"";
    int needed = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (needed <= 0) return L"";
    std::wstring output(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed);
    return output;
}

static std::string filename_from_path(const std::wstring& path) {
    if (path.empty()) return "";
    return wide_to_utf8(fs::path(path).filename().wstring());
}

static std::string json_escape(const std::string& text) {
    std::ostringstream out;
    for (char ch : text) {
        switch (ch) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default: out << ch; break;
        }
    }
    return out.str();
}

static std::string json_unescape(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size(); ++i) {
        char ch = text[i];
        if (ch != '\\' || i + 1 >= text.size()) {
            out.push_back(ch);
            continue;
        }
        char next = text[++i];
        switch (next) {
        case '\\': out.push_back('\\'); break;
        case '"': out.push_back('"'); break;
        case 'n': out.push_back('\n'); break;
        case 'r': out.push_back('\r'); break;
        case 't': out.push_back('\t'); break;
        default: out.push_back(next); break;
        }
    }
    return out;
}

static std::string read_text(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

static std::vector<uint8_t> read_binary(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
}

static std::vector<uint8_t> read_binary_range(const fs::path& path, std::uint64_t offset, std::uint64_t size) {
    if (size == 0u) return {};
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return {};
    stream.seekg(0, std::ios::end);
    const std::streamoff end = static_cast<std::streamoff>(stream.tellg());
    if (end <= 0) return {};
    const std::uint64_t file_size = static_cast<std::uint64_t>(end);
    if (offset >= file_size) return {};
    const std::uint64_t available = file_size - offset;
    const std::uint64_t read_size = std::min(size, available);
    std::vector<uint8_t> data(static_cast<size_t>(read_size));
    stream.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
    stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    data.resize(static_cast<size_t>(std::max<std::streamsize>(0, stream.gcount())));
    return data;
}

static bool write_status(const fs::path& path, const std::string& payload) {
    if (path.empty()) return true;
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    fs::path temp = path;
    temp += L".tmp";
    std::ofstream stream(temp, std::ios::binary);
    if (!stream) return false;
    stream.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    stream.close();
    if (!stream) {
        fs::remove(temp, ec);
        return false;
    }
    if (!MoveFileExW(
            temp.c_str(),
            path.c_str(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        fs::remove(temp, ec);
        return false;
    }
    return true;
}

static std::string write_i32_temp_descriptor_json(const std::vector<int>& values, int components, const wchar_t* label) {
    if (values.empty() || components <= 0 || values.size() % static_cast<size_t>(components) != 0) return std::string();
    std::error_code ec;
    const fs::path root = fs::temp_directory_path(ec);
    if (ec) return std::string();
    static unsigned long long counter = 0;
    const unsigned long long tick = static_cast<unsigned long long>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::wstringstream name;
    name << L"cdmw_mesh_preview_delta_d3d11_" << (label ? label : L"selection")
         << L"_" << GetCurrentProcessId() << L"_" << tick << L"_" << counter++ << L".bin";
    const fs::path path = root / name.str();
    {
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) return std::string();
        for (int value : values) {
            const std::int32_t raw = static_cast<std::int32_t>(value);
            output.write(reinterpret_cast<const char*>(&raw), static_cast<std::streamsize>(sizeof(raw)));
        }
        if (!output) {
            fs::remove(path, ec);
            return std::string();
        }
    }
    std::ostringstream out;
    out << "{\"path\":\"" << json_escape(wide_to_utf8(path.wstring()))
        << "\",\"count\":" << (values.size() / static_cast<size_t>(components))
        << ",\"components\":" << components
        << ",\"type\":\"i32\",\"delete_after\":true}";
    return out.str();
}

static std::string write_f32_temp_descriptor_json(const std::vector<float>& values, int components, const wchar_t* label) {
    if (values.empty() || components <= 0 || values.size() % static_cast<size_t>(components) != 0) return std::string();
    std::error_code ec;
    const fs::path root = fs::temp_directory_path(ec);
    if (ec) return std::string();
    static unsigned long long counter = 0;
    const unsigned long long tick = static_cast<unsigned long long>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::wstringstream name;
    name << L"cdmw_mesh_preview_delta_d3d11_" << (label ? label : L"values")
         << L"_" << GetCurrentProcessId() << L"_" << tick << L"_" << counter++ << L".bin";
    const fs::path path = root / name.str();
    {
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) return std::string();
        for (float value : values) {
            output.write(reinterpret_cast<const char*>(&value), static_cast<std::streamsize>(sizeof(value)));
        }
        if (!output) {
            fs::remove(path, ec);
            return std::string();
        }
    }
    std::ostringstream out;
    out << "{\"path\":\"" << json_escape(wide_to_utf8(path.wstring()))
        << "\",\"count\":" << (values.size() / static_cast<size_t>(components))
        << ",\"components\":" << components
        << ",\"type\":\"f32\",\"delete_after\":true}";
    return out.str();
}

static bool contiguous_i32_range(const std::vector<int>& values, int& start) {
    if (values.empty()) return false;
    start = values.front();
    if (start < 0) return false;
    for (size_t index = 0; index < values.size(); ++index) {
        if (values[index] != start + static_cast<int>(index)) {
            return false;
        }
    }
    return true;
}

static void write_i32_range_or_descriptor_json(
    std::ostream& out,
    const std::vector<int>& values,
    const char* json_name,
    const char* binary_name,
    const char* start_name,
    const char* count_name,
    const wchar_t* label
) {
    int range_start = -1;
    if (contiguous_i32_range(values, range_start)) {
        out << ",\"" << start_name << "\":" << range_start
            << ",\"" << count_name << "\":" << values.size();
        return;
    }
    const std::string descriptor = write_i32_temp_descriptor_json(values, 1, label);
    if (!values.empty() && !descriptor.empty()) {
        out << ",\"" << binary_name << "\":" << descriptor;
        return;
    }
    out << ",\"" << json_name << "\":[";
    for (size_t index = 0; index < values.size(); ++index) {
        if (index) out << ",";
        out << values[index];
    }
    out << "]";
}

static Args parse_args(int argc, wchar_t** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::wstring key = argv[i];
        auto next = [&]() -> std::wstring {
            if (i + 1 >= argc) return L"";
            return argv[++i];
        };
        if (key == L"--self-test") args.self_test = true;
        else if (key == L"--hidden") args.hidden = true;
        else if (key == L"--backend") args.backend = next();
        else if (key == L"--preview-package") args.preview_package = next();
        else if (key == L"--status-file") args.status_file = next();
        else if (key == L"--theme-background") args.theme_background = wide_to_utf8(next());
        else if (key == L"--theme-text") args.theme_text = wide_to_utf8(next());
        else if (key == L"--crash-dir") args.crash_dir = next();
        else if (key == L"--diagnostic-log") args.diagnostic_log = next();
        else if (key == L"--parent-hwnd") {
            std::wstring value = next();
            wchar_t* end = nullptr;
            args.parent_hwnd = static_cast<uintptr_t>(_wcstoui64(value.c_str(), &end, 0));
        }
    }
    return args;
}

static std::string json_string_field(const std::string& object, const std::string& name, const std::string& fallback = "") {
    std::regex pattern("\"" + name + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    return json_unescape(match[1].str());
}

static int json_int_field(const std::string& object, const std::string& name, int fallback = 0) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(-?\\d+)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return std::stoi(match[1].str());
    } catch (...) {
        return fallback;
    }
}

static std::uint64_t json_uint64_field(const std::string& object, const std::string& name, std::uint64_t fallback = 0) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(\\d+)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return static_cast<std::uint64_t>(std::stoull(match[1].str()));
    } catch (...) {
        return fallback;
    }
}

static std::uint64_t mesh_edit_revision_field(const std::string& object) {
    const std::uint64_t edit_revision = json_uint64_field(object, "edit_revision", 0);
    return edit_revision > 0 ? edit_revision : json_uint64_field(object, "revision", 0);
}

static bool mesh_edit_revision_is_stale(std::uint64_t revision, std::uint64_t last_applied_revision) {
    return revision > 0 && revision <= last_applied_revision;
}

static bool self_test_mesh_edit_revision_ordering() {
    std::uint64_t last_applied = 0;
    const auto apply = [&last_applied](std::uint64_t revision) {
        if (mesh_edit_revision_is_stale(revision, last_applied)) return false;
        if (revision > 0) last_applied = revision;
        return true;
    };
    return apply(2)
        && !apply(1)
        && !apply(2)
        && apply(4)
        && apply(0)
        && last_applied == 4
        && mesh_edit_revision_field("{\"edit_revision\":7,\"revision\":6}") == 7
        && mesh_edit_revision_field("{\"revision\":5}") == 5;
}

static bool json_bool_field(const std::string& object, const std::string& name, bool fallback = false) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(true|false)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    return match[1].str() == "true";
}

static float json_float_field(const std::string& object, const std::string& name, float fallback = 0.0f) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return std::stof(match[1].str());
    } catch (...) {
        return fallback;
    }
}

static bool json_has_field(const std::string& object, const std::string& name) {
    std::regex pattern("\"" + name + "\"\\s*:");
    return std::regex_search(object, pattern);
}

static std::vector<std::string> objects_with_key(const std::string& text, const std::string& key) {
    std::vector<std::string> objects;
    std::string needle = "\"" + key + "\"";
    size_t search = 0;
    while (true) {
        size_t key_pos = text.find(needle, search);
        if (key_pos == std::string::npos) break;
        size_t start = text.rfind('{', key_pos);
        if (start == std::string::npos) break;
        int depth = 0;
        bool in_string = false;
        bool escaped = false;
        size_t end = std::string::npos;
        for (size_t i = start; i < text.size(); ++i) {
            char ch = text[i];
            if (escaped) {
                escaped = false;
                continue;
            }
            if (ch == '\\' && in_string) {
                escaped = true;
                continue;
            }
            if (ch == '"') {
                in_string = !in_string;
                continue;
            }
            if (in_string) continue;
            if (ch == '{') ++depth;
            else if (ch == '}') {
                --depth;
                if (depth == 0) {
                    end = i;
                    break;
                }
            }
        }
        if (end == std::string::npos) break;
        objects.push_back(text.substr(start, end - start + 1));
        search = end + 1;
    }
    return objects;
}

static std::wstring absolute_from_manifest_path(const fs::path& package_dir, const std::string& value) {
    if (value.empty()) return L"";
    fs::path path = utf8_to_wide(value);
    if (path.is_relative()) path = package_dir / path;
    return path.wstring();
}

static std::string json_object_field(const std::string& object, const std::string& name);

static std::wstring dds_slot_source(const std::string& object, const std::string& slot) {
    const std::string descriptor = json_object_field(object, slot);
    if (descriptor.empty()) return L"";
    if (!json_bool_field(descriptor, "available", true)) return L"";
    if (!json_bool_field(descriptor, "direct_upload_candidate", true)) return L"";
    return utf8_to_wide(json_string_field(descriptor, "source_path"));
}

static std::wstring texture_slot_relative(const fs::path& package_dir, const std::string& object, const std::string& slot) {
    std::regex textures_pattern("\"textures\"\\s*:\\s*\\{([^{}]*)\\}");
    std::smatch textures_match;
    if (!std::regex_search(object, textures_match, textures_pattern)) return L"";
    std::string textures_object = textures_match[1].str();
    return absolute_from_manifest_path(package_dir, json_string_field(textures_object, slot));
}

static std::vector<std::string> json_string_array_field(const std::string& object, const std::string& name) {
    std::vector<std::string> values;
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return values;
    std::string array_text = match[1].str();
    std::regex item_pattern("\"((?:\\\\.|[^\"])*)\"");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        values.push_back(json_unescape((*it)[1].str()));
    }
    return values;
}

static std::vector<int> json_int_array_field(const std::string& object, const std::string& name) {
    std::vector<int> values;
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return values;
    std::string array_text = match[1].str();
    std::regex item_pattern("-?\\d+");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        try {
            values.push_back(std::stoi(it->str()));
        } catch (...) {
        }
    }
    return values;
}

static std::vector<int> json_int_values_in_array_field(const std::string& object, const std::string& name) {
    std::vector<int> values;
    const std::string marker = "\"" + name + "\"";
    size_t name_pos = object.find(marker);
    if (name_pos == std::string::npos) return values;
    size_t colon = object.find(':', name_pos + marker.size());
    if (colon == std::string::npos) return values;
    size_t array_start = object.find('[', colon + 1);
    if (array_start == std::string::npos) return values;
    bool in_string = false;
    bool escaped = false;
    int depth = 0;
    size_t array_end = std::string::npos;
    for (size_t i = array_start; i < object.size(); ++i) {
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
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '[') ++depth;
        else if (ch == ']') {
            --depth;
            if (depth == 0) {
                array_end = i;
                break;
            }
        }
    }
    if (array_end == std::string::npos || array_end <= array_start) return values;
    const std::string array_text = object.substr(array_start + 1u, array_end - array_start - 1u);
    std::regex item_pattern("-?\\d+");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        try {
            values.push_back(std::stoi(it->str()));
        } catch (...) {
        }
    }
    return values;
}

static std::vector<float> json_float_array_field(const std::string& object, const std::string& name) {
    std::vector<float> values;
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return values;
    std::string array_text = match[1].str();
    std::regex item_pattern("-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        try {
            values.push_back(std::stof(it->str()));
        } catch (...) {
        }
    }
    return values;
}

static std::string json_object_field(const std::string& object, const std::string& name) {
    const std::string marker = "\"" + name + "\"";
    size_t name_pos = object.find(marker);
    if (name_pos == std::string::npos) return "";
    size_t colon = object.find(':', name_pos + marker.size());
    if (colon == std::string::npos) return "";
    size_t object_start = object.find('{', colon + 1);
    if (object_start == std::string::npos) return "";
    bool in_string = false;
    bool escaped = false;
    int depth = 0;
    for (size_t i = object_start; i < object.size(); ++i) {
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
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '{') {
            ++depth;
            continue;
        }
        if (ch == '}') {
            --depth;
            if (depth == 0) {
                return object.substr(object_start + 1, i - object_start - 1);
            }
        }
    }
    return "";
}

static std::string json_binary_payload_path_field(const std::string& object, const std::string& name) {
    const std::string descriptor = json_object_field(object, name);
    if (!descriptor.empty()) {
        return json_string_field(descriptor, "path");
    }
    return json_string_field(object, name);
}

static bool json_binary_payload_delete_after_field(const std::string& object, const std::string& name) {
    const std::string descriptor = json_object_field(object, name);
    return !descriptor.empty() && json_bool_field(descriptor, "delete_after", false);
}

static void delete_json_binary_payload_if_requested(const std::string& object, const std::string& name) {
    if (!json_binary_payload_delete_after_field(object, name)) return;
    const std::string path_text = json_binary_payload_path_field(object, name);
    if (path_text.empty()) return;
    const fs::path path = utf8_to_wide(path_text);
    const std::wstring filename = path.filename().wstring();
    if (filename.rfind(L"cdmw_mesh_preview_delta_", 0) != 0) return;
    std::error_code ec;
    fs::remove(path, ec);
}

static std::vector<uint8_t> json_binary_payload_bytes_field(
    const std::string& object,
    const std::string& name,
    size_t element_size
) {
    const std::string path_text = json_binary_payload_path_field(object, name);
    if (path_text.empty()) return {};
    std::vector<uint8_t> bytes = read_binary(utf8_to_wide(path_text));
    delete_json_binary_payload_if_requested(object, name);
    if (element_size == 0u || bytes.empty() || bytes.size() % element_size != 0u) return {};
    return bytes;
}

static std::vector<float> json_f64_array_or_json_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name,
    int components
) {
    const std::vector<uint8_t> bytes = json_binary_payload_bytes_field(
        object,
        binary_name,
        sizeof(double) * static_cast<size_t>(std::max(1, components)));
    if (bytes.empty()) return json_float_array_field(object, json_name);
    const size_t count = bytes.size() / sizeof(double);
    std::vector<float> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        double raw = 0.0;
        std::memcpy(&raw, bytes.data() + index * sizeof(double), sizeof(double));
        if (!std::isfinite(raw)) return {};
        values.push_back(static_cast<float>(raw));
    }
    return values;
}

static std::vector<int> json_i32_array_or_json_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name
) {
    const std::vector<uint8_t> bytes = json_binary_payload_bytes_field(object, binary_name, sizeof(std::int32_t));
    if (bytes.empty()) return json_int_array_field(object, json_name);
    const size_t count = bytes.size() / sizeof(std::int32_t);
    std::vector<int> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        std::int32_t raw = 0;
        std::memcpy(&raw, bytes.data() + index * sizeof(std::int32_t), sizeof(std::int32_t));
        values.push_back(static_cast<int>(raw));
    }
    return values;
}

static std::vector<int> json_i32_range_or_array_or_json_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name,
    const std::string& start_name,
    const std::string& count_name
) {
    std::vector<int> values = json_i32_array_or_json_field(object, binary_name, json_name);
    if (!values.empty()) return values;
    const int start = json_int_field(object, start_name, -1);
    const int count = json_int_field(object, count_name, 0);
    if (start < 0 || count <= 0) return values;
    values.reserve(static_cast<size_t>(count));
    for (int offset = 0; offset < count; ++offset) {
        values.push_back(start + offset);
    }
    return values;
}

static std::vector<int> json_i32_array_or_json_values_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name
) {
    const std::vector<uint8_t> bytes = json_binary_payload_bytes_field(object, binary_name, sizeof(std::int32_t));
    if (bytes.empty()) return json_int_values_in_array_field(object, json_name);
    const size_t count = bytes.size() / sizeof(std::int32_t);
    std::vector<int> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        std::int32_t raw = 0;
        std::memcpy(&raw, bytes.data() + index * sizeof(std::int32_t), sizeof(std::int32_t));
        values.push_back(static_cast<int>(raw));
    }
    return values;
}

static bool self_test_i32_descriptor_reader() {
    std::error_code ec;
    const fs::path path = fs::temp_directory_path(ec) / L"cdmw_mesh_preview_delta_self_test_selection.bin";
    if (ec) return false;
    {
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) return false;
        const std::int32_t values[3] = {2, 4, 6};
        output.write(reinterpret_cast<const char*>(values), static_cast<std::streamsize>(sizeof(values)));
        if (!output) return false;
    }
    std::ostringstream payload;
    payload << "{\"source_vertex_indices_binary\":{\"path\":\"" << json_escape(wide_to_utf8(path.wstring()))
            << "\",\"count\":3,\"components\":1,\"type\":\"i32\",\"delete_after\":true}}";
    const std::vector<int> parsed = json_i32_array_or_json_field(payload.str(), "source_vertex_indices_binary", "source_vertex_indices");
    const std::vector<int> parsed_range = json_i32_range_or_array_or_json_field(
        "{\"source_vertex_start\":5,\"source_vertex_count\":3}",
        "source_vertex_indices_binary",
        "source_vertex_indices",
        "source_vertex_start",
        "source_vertex_count");
    const bool removed = !fs::exists(path, ec);
    const std::string edge_descriptor = write_i32_temp_descriptor_json(std::vector<int>({1, 2, 2, 3}), 2, L"self_test_edges");
    if (edge_descriptor.empty()) return false;
    const std::string edge_payload = std::string("{\"source_edges_binary\":") + edge_descriptor + "}";
    const std::vector<int> parsed_edges = json_i32_array_or_json_values_field(edge_payload, "source_edges_binary", "source_edges");
    const std::string edge_path = json_string_field(edge_descriptor, "path");
    const bool edge_removed = edge_path.empty() || !fs::exists(utf8_to_wide(edge_path), ec);
    const std::string weight_descriptor = write_f32_temp_descriptor_json(std::vector<float>({0.25f, 1.0f}), 1, L"self_test_weights");
    if (weight_descriptor.empty()) return false;
    const std::string weight_payload = std::string("{\"source_vertex_weights_binary\":") + weight_descriptor + "}";
    const std::vector<uint8_t> weight_bytes = json_binary_payload_bytes_field(weight_payload, "source_vertex_weights_binary", sizeof(float));
    std::vector<float> parsed_weights;
    for (size_t index = 0; index + sizeof(float) <= weight_bytes.size(); index += sizeof(float)) {
        float raw = 0.0f;
        std::memcpy(&raw, weight_bytes.data() + index, sizeof(float));
        parsed_weights.push_back(raw);
    }
    const std::string weight_path = json_string_field(weight_descriptor, "path");
    const bool weight_removed = weight_path.empty() || !fs::exists(utf8_to_wide(weight_path), ec);
    return parsed == std::vector<int>({2, 4, 6})
        && parsed_range == std::vector<int>({5, 6, 7})
        && removed
        && parsed_edges == std::vector<int>({1, 2, 2, 3})
        && edge_removed
        && parsed_weights == std::vector<float>({0.25f, 1.0f})
        && weight_removed;
}

static std::vector<std::string> json_object_array_field(const std::string& object, const std::string& name) {
    std::vector<std::string> values;
    const std::string marker = "\"" + name + "\"";
    size_t name_pos = object.find(marker);
    if (name_pos == std::string::npos) return values;
    size_t colon = object.find(':', name_pos + marker.size());
    if (colon == std::string::npos) return values;
    size_t array_start = object.find('[', colon + 1);
    if (array_start == std::string::npos) return values;
    bool in_string = false;
    bool escaped = false;
    int array_depth = 0;
    int object_depth = 0;
    size_t item_start = std::string::npos;
    for (size_t i = array_start; i < object.size(); ++i) {
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
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '[') {
            ++array_depth;
            continue;
        }
        if (ch == ']') {
            --array_depth;
            if (array_depth <= 0) break;
            continue;
        }
        if (array_depth != 1) continue;
        if (ch == '{') {
            if (object_depth == 0) item_start = i;
            ++object_depth;
            continue;
        }
        if (ch == '}' && object_depth > 0) {
            --object_depth;
            if (object_depth == 0 && item_start != std::string::npos) {
                values.push_back(object.substr(item_start, i - item_start + 1));
                item_start = std::string::npos;
            }
        }
    }
    return values;
}

static void delete_mesh_edit_payload_descriptors(const std::string& payload) {
    for (const std::string& group : json_object_array_field(payload, "groups")) {
        for (const char* name : {
                 "source_vertex_indices_binary",
                 "positions_binary",
                 "normals_binary",
                 "uvs_binary"}) {
            delete_json_binary_payload_if_requested(group, name);
        }
    }
}
