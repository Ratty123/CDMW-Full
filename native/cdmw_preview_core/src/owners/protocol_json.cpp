constexpr int kNativePackageSchemaVersion = 8;
constexpr int kNativeMaterialGraphVersion = 4;
constexpr int kNativeMaterialSemanticsVersion = 10;
constexpr int kNativeDdsExtractionVersion = 2;

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 8);
    for (char ch : value) {
        switch (ch) {
        case '\\': out += "\\\\"; break;
        case '"': out += "\\\""; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20) {
                out += ' ';
            } else {
                out += ch;
            }
            break;
        }
    }
    return out;
}

std::string read_text(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open " + path.string());
    }
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void write_text(const fs::path& path, const std::string& text) {
    if (!path.parent_path().empty()) {
        fs::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("could not write " + path.string());
    }
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
}

std::vector<char> read_binary_file(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open " + path.string());
    }
    return std::vector<char>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

std::string find_string_value(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return {};
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) return {};
    std::string out;
    bool escaped = false;
    for (size_t i = pos + 1; i < json.size(); ++i) {
        char ch = json[i];
        if (escaped) {
            switch (ch) {
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            default: out += ch; break;
            }
            escaped = false;
            continue;
        }
        if (ch == '\\') {
            escaped = true;
            continue;
        }
        if (ch == '"') break;
        out += ch;
    }
    return out;
}

std::string find_object_value(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return {};
    pos = json.find('{', pos + 1);
    if (pos == std::string::npos) return {};
    int depth = 0;
    bool in_string = false;
    bool escaped = false;
    for (size_t i = pos; i < json.size(); ++i) {
        const char ch = json[i];
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '{') {
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0) return json.substr(pos, i - pos + 1);
        }
    }
    return {};
}

static std::vector<std::string> find_object_array_values(
    const std::string& json,
    const std::string& key,
    size_t max_count,
    bool& truncated
) {
    std::vector<std::string> values;
    truncated = false;
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return values;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return values;
    const size_t array_start = json.find('[', pos + 1);
    if (array_start == std::string::npos) return values;
    bool in_string = false;
    bool escaped = false;
    int array_depth = 0;
    int object_depth = 0;
    size_t item_start = std::string::npos;
    for (size_t i = array_start; i < json.size(); ++i) {
        const char ch = json[i];
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
        } else if (ch == '}' && object_depth > 0) {
            --object_depth;
            if (object_depth == 0 && item_start != std::string::npos) {
                if (values.size() < max_count) {
                    values.push_back(json.substr(item_start, i - item_start + 1));
                } else {
                    truncated = true;
                }
                item_start = std::string::npos;
            }
        }
    }
    return values;
}

static std::vector<std::string> find_string_array_values(
    const std::string& json,
    const std::string& key,
    size_t max_count,
    bool& truncated
) {
    std::vector<std::string> values;
    truncated = false;
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return values;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return values;
    pos = json.find('[', pos + 1);
    if (pos == std::string::npos) return values;
    ++pos;
    while (pos < json.size()) {
        while (pos < json.size() && (std::isspace(static_cast<unsigned char>(json[pos])) || json[pos] == ',')) ++pos;
        if (pos >= json.size() || json[pos] == ']') break;
        if (json[pos] != '"') return values;
        ++pos;
        std::string value;
        bool escaped = false;
        for (; pos < json.size(); ++pos) {
            const char ch = json[pos];
            if (escaped) {
                switch (ch) {
                case 'n': value += '\n'; break;
                case 'r': value += '\r'; break;
                case 't': value += '\t'; break;
                default: value += ch; break;
                }
                escaped = false;
                continue;
            }
            if (ch == '\\') {
                escaped = true;
                continue;
            }
            if (ch == '"') {
                ++pos;
                break;
            }
            value += ch;
        }
        if (values.size() < max_count) values.push_back(std::move(value));
        else truncated = true;
    }
    return values;
}

long long find_int_value(const std::string& json, const std::string& key, long long fallback = 0) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return fallback;
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    bool negative = false;
    if (pos < json.size() && json[pos] == '-') {
        negative = true;
        ++pos;
    }
    long long value = 0;
    bool any = false;
    while (pos < json.size() && std::isdigit(static_cast<unsigned char>(json[pos]))) {
        any = true;
        value = value * 10 + (json[pos] - '0');
        ++pos;
    }
    if (!any) return fallback;
    return negative ? -value : value;
}

bool find_bool_value(const std::string& json, const std::string& key, bool fallback = false) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return fallback;
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    if (json.compare(pos, 4, "true") == 0) return true;
    if (json.compare(pos, 5, "false") == 0) return false;
    if (pos < json.size() && (json[pos] == '0' || json[pos] == '1')) return json[pos] != '0';
    return fallback;
}

float find_float_value(const std::string& json, const std::string& key, float fallback = 0.0f) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return fallback;
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    const size_t start = pos;
    if (pos < json.size() && (json[pos] == '-' || json[pos] == '+')) ++pos;
    bool any = false;
    while (pos < json.size() && std::isdigit(static_cast<unsigned char>(json[pos]))) {
        any = true;
        ++pos;
    }
    if (pos < json.size() && json[pos] == '.') {
        ++pos;
        while (pos < json.size() && std::isdigit(static_cast<unsigned char>(json[pos]))) {
            any = true;
            ++pos;
        }
    }
    if (pos < json.size() && (json[pos] == 'e' || json[pos] == 'E')) {
        ++pos;
        if (pos < json.size() && (json[pos] == '-' || json[pos] == '+')) ++pos;
        while (pos < json.size() && std::isdigit(static_cast<unsigned char>(json[pos]))) ++pos;
    }
    if (!any) return fallback;
    try {
        return std::stof(json.substr(start, pos - start));
    } catch (...) {
        return fallback;
    }
}

std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

std::string upper_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    return value;
}

static std::string normalize_visible_texture_mode(const std::string& mode);

std::string basename_extension(const std::string& path) {
    const size_t slash = path.find_last_of("/\\");
    const size_t dot = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot < slash)) return {};
    return lower_copy(path.substr(dot));
}

static std::string extension_from_path(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    size_t dot = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot < slash)) return "";
    return lower_copy(path.substr(dot));
}

static std::string basename_from_path(const std::string& path) {
    size_t slash = path.find_last_of("/\\");
    return slash == std::string::npos ? path : path.substr(slash + 1);
}

static std::string dirname_from_path(const std::string& path) {
    const size_t slash = path.find_last_of("/\\");
    return slash == std::string::npos ? "" : path.substr(0, slash);
}

static std::string stem_from_path(const std::string& path) {
    std::string base = basename_from_path(path);
    const std::string ext = extension_from_path(base);
    if (!ext.empty() && base.size() > ext.size()) {
        base.resize(base.size() - ext.size());
    }
    return base;
}

struct ArchiveEntryRef {
    std::string path;
    std::string basename;
    std::string extension;
    fs::path pamt_path;
    fs::path paz_file;
    std::uint64_t offset = 0;
    std::uint64_t comp_size = 0;
    std::uint64_t orig_size = 0;
    std::uint32_t flags = 0;
    std::uint32_t paz_index = 0;
    fs::path prepared_path;
    std::string prepared_sha256;
    std::int64_t prepared_size = -1;

    int compression_type() const {
        return static_cast<int>(flags & 0x0F);
    }

    bool compressed() const {
        return comp_size != orig_size;
    }

    bool encrypted() const {
        return (flags >> 4) != 0;
    }

    int encryption_type() const {
        return static_cast<int>((flags >> 4) & 0x0F);
    }
};

struct PreviewContextComponentRef {
    ArchiveEntryRef entry;
    std::string slot, label, authority, appearance_path;
    float scale = 1.0f;
    fs::path presentation_geometry_path;
    std::string presentation_geometry_source;
};

struct EntryJob {
    std::string path;
    std::string extension;
    fs::path paz_file;
    std::uint64_t offset = 0;
    std::uint64_t comp_size = 0;
    std::uint64_t orig_size = 0;
    std::uint32_t flags = 0;
    fs::path output_root;
    fs::path cache_root;
    fs::path package_root;
    fs::path archive_index_path;
    fs::path archive_basename_index_path;
    int schema_version = 4;
    ArchiveEntryRef entry;
    ArchiveEntryRef companion_entry;
    std::vector<ArchiveEntryRef> archive_dependency_entries;
    bool archive_dependency_entries_complete = false;
    std::vector<std::string> enabled_prefab_component_paths;
    std::map<std::string, int> model_property_indices;
    std::vector<PreviewContextComponentRef> preview_context_components;
    fs::path presentation_geometry_path;
    std::string presentation_geometry_source;
    bool use_textures = true;
    bool high_quality_textures = true;
    bool disable_all_support_maps = false;
    bool disable_normal_map = false;
    bool disable_material_map = false;
    bool disable_height_map = false;
    bool flip_texture_v = false;
    float normal_strength_cap = 1.0f;
    float height_effect_max = 1.0f;
    int max_anisotropy = 16;
    float d3d11_mip_lod_bias = -2.0f;
    std::string d3d11_view_mode = "lit";
    bool d3d11_cull_back_faces = false;
    float d3d11_light_azimuth_degrees = -10.0f;
    float d3d11_light_elevation_degrees = 0.0f;
    std::string d3d11_normal_y_mode = "asset";
    float d3d11_ao_strength = 0.45f;
    float d3d11_roughness_bias = -0.04f;
    float d3d11_metalness_scale = 1.45f;
    float d3d11_environment_strength = 0.62f;
    float d3d11_emissive_gain = 2.2f;
    float d3d11_tone_exposure = 1.00f;
    float d3d11_tone_contrast = 1.08f;
    float d3d11_tone_gamma = 1.00f;
    std::string d3d11_texture_address_mode = "wrap";
    float ambient_strength = 0.84f;
    float diffuse_wrap_bias = 0.58f;
    float diffuse_light_scale = 0.62f;
    float specular_base = 0.055f;
    float specular_max = 0.52f;
    float shininess_min = 28.0f;
    float shininess_max = 152.0f;
    float orbit_sensitivity = 0.22f;
    float pan_sensitivity = 0.60f;
    bool invert_orbit_x = false;
    bool invert_orbit_y = false;
    bool invert_pan_x = false;
    bool invert_pan_y = false;
    std::string visible_texture_mode = "mesh_base_first";
    std::string render_diagnostic_mode = "lit";
};

static std::string native_lighting_preset_for_job(const EntryJob& job, bool has_metal_preview_response) {
    const std::string view_mode = lower_copy(job.d3d11_view_mode);
    if (view_mode == "game_outdoor" || view_mode == "cd_outdoor" || view_mode == "outdoor_game") return "game_outdoor_approx";
    const std::string diagnostic_mode = lower_copy(job.render_diagnostic_mode);
    if (
        diagnostic_mode == "texture_probe"
        || diagnostic_mode == "base_direct"
        || diagnostic_mode == "base_no_tint"
        || diagnostic_mode == "normal_raw"
        || diagnostic_mode == "material_raw"
        || diagnostic_mode == "height_raw"
        || diagnostic_mode == "uv_checker"
    ) {
        return "texture_debug";
    }
    if (diagnostic_mode == "metal_shine" || diagnostic_mode == "roughness_response" || diagnostic_mode == "material_response") {
        return "shiny_metal_inspection";
    }
    if (diagnostic_mode == "rich_lit" || diagnostic_mode == "height_depth" || diagnostic_mode == "height_calibrated") {
        return "cloth_skin_inspection";
    }
    return has_metal_preview_response ? "shiny_metal_inspection" : "neutral_studio";
}

ArchiveEntryRef parse_archive_entry_ref(const std::string& object) {
    ArchiveEntryRef entry;
    entry.path = find_string_value(object, "path");
    entry.basename = find_string_value(object, "basename");
    if (entry.basename.empty()) entry.basename = basename_from_path(entry.path);
    entry.extension = find_string_value(object, "extension");
    if (entry.extension.empty()) entry.extension = extension_from_path(entry.path);
    entry.pamt_path = fs::path(find_string_value(object, "pamt_path"));
    entry.paz_file = fs::path(find_string_value(object, "paz_file"));
    entry.offset = static_cast<std::uint64_t>(std::max<long long>(0, find_int_value(object, "offset")));
    entry.comp_size = static_cast<std::uint64_t>(std::max<long long>(0, find_int_value(object, "comp_size")));
    entry.orig_size = static_cast<std::uint64_t>(std::max<long long>(0, find_int_value(object, "orig_size")));
    entry.flags = static_cast<std::uint32_t>(std::max<long long>(0, find_int_value(object, "flags")));
    entry.paz_index = static_cast<std::uint32_t>(std::max<long long>(0, find_int_value(object, "paz_index")));
    entry.prepared_path = fs::path(find_string_value(object, "prepared_path"));
    entry.prepared_sha256 = lower_copy(find_string_value(object, "prepared_sha256"));
    entry.prepared_size = find_int_value(object, "prepared_size", -1);
    return entry;
}

static PreviewContextComponentRef parse_preview_context_component_ref(const std::string& object) {
    PreviewContextComponentRef component;
    component.entry = parse_archive_entry_ref(find_object_value(object, "entry"));
    component.slot = lower_copy(find_string_value(object, "slot"));
    component.label = find_string_value(object, "label");
    component.authority = lower_copy(find_string_value(object, "authority"));
    component.appearance_path = find_string_value(object, "appearance_path");
    component.scale = std::clamp(find_float_value(object, "scale", 1.0f), 0.01f, 100.0f);
    component.presentation_geometry_path = fs::path(find_string_value(object, "context_presentation_geometry_path"));
    component.presentation_geometry_source = find_string_value(object, "context_presentation_geometry_source");
    if (component.entry.path.empty()) throw std::runtime_error("preview context component is missing its archive entry");
    if (component.slot != "face" && component.slot != "hair"
        && component.slot != "body" && component.slot != "gear") {
        throw std::runtime_error("preview context component has an unsupported slot");
    }
    if (component.authority != "authored" && component.authority != "compatible")
        throw std::runtime_error("preview context component has an unsupported authority");
    return component;
}

struct Vec2 {
    float x = 0.0f;
    float y = 0.0f;
};

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};
