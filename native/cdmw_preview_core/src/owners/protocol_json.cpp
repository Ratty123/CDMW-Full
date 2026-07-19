constexpr int kNativePackageSchemaVersion = 8;
constexpr int kNativeMaterialGraphVersion = 3;
constexpr int kNativeMaterialSemanticsVersion = 6;
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
    return entry;
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

struct ParSection {
    int index = 0;
    std::uint32_t offset = 0;
    std::uint32_t size = 0;
};

struct PacDescriptor {
    std::string name;
    std::string material;
    Vec3 bbox_min;
    Vec3 bbox_extent;
    std::array<std::uint32_t, 10> vertex_counts{};
    std::array<std::uint32_t, 10> index_counts{};
    int stored_lod_count = 0;
    std::uint32_t descriptor_offset = 0;
};

struct NativeSubmesh {
    std::string name;
    std::string material;
    std::string source_model_path;
    std::string source_component_label;
    std::vector<Vec3> positions;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    std::vector<std::uint32_t> indices;
    std::vector<std::int32_t> source_vertex_indices;
    int source_submesh_index = -1;
    int source_local_submesh_index = -1;
    int source_component_index = 0;
    bool source_prefab_component = false;
    std::string vertex_layout_name;
    int vertex_stride = 40;
    int uv_offset = 8;
    int normal_offset = 16;
    float uv_finite_ratio = 0.0f;
    float uv_span_u = 0.0f;
    float uv_span_v = 0.0f;
    float uv_abs_max = 0.0f;
    float uv_edge_outlier_ratio = 0.0f;
    float uv_degenerate_triangle_ratio = 0.0f;
    float degenerate_triangle_ratio = 0.0f;
    float edge_outlier_ratio = 0.0f;
    float normal_valid_ratio = 0.0f;
    float geometry_quality_score = 0.0f;
    bool geometry_safe = true;
    std::string geometry_quality_note;
};

struct NativePbdSidecarHint {
    std::string simulation_material_name;
    std::string material_name;
    std::string submesh_name;
    std::string parameter_name;
    std::string sidecar_path;
    std::string simulation_kind = "unknown";
};

struct NativePbdConfigMaterial {
    std::string name;
    std::string filename;
    std::string mode;
    std::string pbd_part;
};

struct NativePbdMaterialSettings {
    std::string material_name;
    std::string material_path;
    std::string simulation_kind = "cloth";
    float stretching_stiffness = 0.30f;
    float bending_stiffness = 0.18f;
    float damping = 0.65f;
    float gravity = -10.0f;
    float air_resistance = 1.0f;
    float wind_response = 0.40f;
    int solver_iterations = 30;
    bool collision_enabled = true;
    bool is_cloak = false;
};

struct NativeClothConstraint {
    int a = 0;
    int b = 0;
    float rest_length = 0.0f;
    float stiffness = 0.0f;
};

struct NativeClothRuntimeBatch {
    bool active = false;
    NativePbdSidecarHint hint;
    NativePbdMaterialSettings settings;
    fs::path particle_path;
    fs::path pin_path;
    fs::path constraint_path;
    int particle_count = 0;
    int constraint_count = 0;
};

struct TextureBinding {
    std::string role;
    std::string source_path;
    std::string archive_path;
    std::string texture_name;
    std::string parameter_name;
    std::string semantic_type;
    std::string semantic_subtype;
    std::string shader_family;
    std::string shader_rule;
    std::string material_name;
    std::string sidecar_path;
    std::string sidecar_kind;
    std::string linked_mesh_path;
    std::string packed_channels;
    std::string material_output_quality = "inferred";
    std::string srgb_mode = "auto";
    std::string parameter_declared_by;
    std::string visible_class = "visible_generic";
    std::string source_authority = "sidecar";
    std::string relation_confidence = "derived_same_stem";
    std::string relation_reason = "Recovered by native material index.";
    std::string layer_role;
    std::string layer_channel;
    std::string evidence_grade = "corpus_inferred";
    std::string blend_flags;
    std::string material_parameter_names;
    std::string pbd_simulation_material_name;
    std::string pbd_simulation_kind;
    std::string pbd_material_name;
    std::string pbd_submesh_name;
    int material_wrapper_index = -1;
    int material_wrapper_count = 0;
    bool material_wrapper_order_authoritative = false;
    bool alpha_test_enabled = false;
    float layer_weight = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    float emissive_intensity_hint = 0.0f;
    std::array<float, 4> tint_color{1.0f, 1.0f, 1.0f, 1.0f};
    int dds_width = 0;
    int dds_height = 0;
    std::string dds_format = "";
};

struct MaterialParameterRecord {
    std::string kind;
    std::string name;
    std::string value;
    float numeric_value = 0.0f;
    bool has_numeric = false;
};

struct MaterialLayer {
    std::string layer_role;
    std::string layer_channel = "r";
    std::string shader_family;
    std::string shader_rule;
    std::string evidence_grade = "corpus_inferred";
    std::string blend_order = "base_then_layer";
    std::string source_parameter;
    std::string mask_parameter;
    std::string diffuse_source;
    std::string diffuse_archive_path;
    std::string normal_source;
    std::string normal_archive_path;
    std::string material_source;
    std::string material_archive_path;
    std::string height_source;
    std::string height_archive_path;
    std::string mask_source;
    std::string mask_archive_path;
    std::string roughness_hint_source;
    std::string metallic_hint_source;
    std::string specular_hint_source;
    float weight = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    std::array<float, 4> tint{1.0f, 1.0f, 1.0f, 1.0f};
};

struct NativeAssetFamilyRow {
    std::string group;
    std::string role;
    std::string display_name;
    std::string path;
    std::string status = "Resolved";
    std::string evidence = "Hint";
    std::string confidence = "derived_same_stem";
    std::string include_policy = "manual";
    std::string reason;
    std::string relation_kind = "metadata";
    std::string semantic_label;
    std::string semantic_hint;
    std::string sidecar_parameter_name;
    std::string material_name;
    std::string package_label;
    std::string sidecar_kind;
    std::string shader_family;
    std::string texture_role;
    std::string source_table;
    std::string source_field;
};

struct NativePackage {
    fs::path path;
    int batch_count = 0;
    int vertex_count = 0;
    int face_count = 0;
    int dds_candidates = 0;
    int dds_extracted = 0;
    double pamt_index_ms = 0.0;
    size_t pamt_index_entries = 0;
    bool pamt_index_cache_hit = false;
    std::string pamt_index_cache_path;
    std::string mesh_parse = "unsupported";
    std::string material_index = "none";
    std::string material_graph_status = "not_started";
    std::string material_graph_cache_path;
    bool material_graph_cache_hit = false;
    std::string texture_resolution = "none";
    std::string material_output_quality = "approximate";
    std::vector<std::string> notes;
    int lod_count = 0;
    bool material_quality_safe = true;
    int base_missing_count = 0;
    int base_low_res_count = 0;
    int base_low_confidence_count = 0;
    int base_technical_count = 0;
    int pbd_hint_count = 0;
    int pbd_soft_hint_count = 0;
    int pbd_cloth_hint_count = 0;
    std::vector<std::string> base_quality_notes;
    std::vector<std::string> selected_texture_examples;
    std::vector<std::string> rejected_texture_examples;
    std::vector<NativeAssetFamilyRow> asset_family_rows;
    int asset_family_reference_count = 0;
};

static std::uint16_t read_u16(const std::vector<char>& data, size_t offset) {
    if (offset + 2 > data.size()) throw std::runtime_error("u16 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

static std::int16_t read_i16(const std::vector<char>& data, size_t offset) {
    return static_cast<std::int16_t>(read_u16(data, offset));
}

static std::uint32_t read_u32(const std::vector<char>& data, size_t offset) {
    if (offset + 4 > data.size()) throw std::runtime_error("u32 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint32_t>(p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24));
}

static float read_f32(const std::vector<char>& data, size_t offset) {
    std::uint32_t raw = read_u32(data, offset);
    float value = 0.0f;
    std::memcpy(&value, &raw, sizeof(float));
    return value;
}

static float half_to_float(std::uint16_t value) {
    const std::uint32_t sign = (static_cast<std::uint32_t>(value & 0x8000u)) << 16;
    std::uint32_t exponent = (value >> 10) & 0x1Fu;
    std::uint32_t mantissa = value & 0x03FFu;
    std::uint32_t out = 0;
    if (exponent == 0) {
        if (mantissa == 0) {
            out = sign;
        } else {
            exponent = 1;
            while ((mantissa & 0x0400u) == 0) {
                mantissa <<= 1;
                --exponent;
            }
            mantissa &= 0x03FFu;
            out = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
        }
    } else if (exponent == 31) {
        out = sign | 0x7F800000u | (mantissa << 13);
    } else {
        out = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
    }
    float result = 0.0f;
    std::memcpy(&result, &out, sizeof(float));
    return std::isfinite(result) ? result : 0.0f;
}

static std::string read_c_string(const std::vector<char>& data, size_t offset, size_t max_length) {
    if (offset >= data.size()) return "";
    const size_t limit = std::min(data.size(), offset + max_length);
    size_t end = offset;
    while (end < limit && data[end] != '\0') ++end;
    if (end <= offset) return "";
    std::string out(data.data() + offset, data.data() + end);
    out.erase(std::remove_if(out.begin(), out.end(), [](unsigned char ch) {
        return ch < 0x20 || ch > 0x7E;
    }), out.end());
    return out;
}

static bool looks_like_dds_string(const std::vector<char>& data, size_t offset, size_t max_length = 256) {
    if (offset >= data.size()) return false;
    if (offset > 0) {
        const unsigned char previous = static_cast<unsigned char>(data[offset - 1]);
        if (previous >= 32 && previous <= 126) return false;
    }
    const size_t limit = std::min(data.size(), offset + max_length);
    size_t end = offset;
    while (end < limit && data[end] != '\0') ++end;
    const size_t length = end - offset;
    if (length <= 4 || length > 255) return false;
    std::string text(data.data() + offset, data.data() + end);
    return lower_copy(text).ends_with(".dds");
}

EntryJob parse_job(const fs::path& job_path) {
    const std::string text = read_text(job_path);
    EntryJob job;
    job.output_root = fs::path(find_string_value(text, "output_root"));
    job.cache_root = fs::path(find_string_value(text, "cache_root"));
    job.package_root = fs::path(find_string_value(text, "package_root"));
    job.archive_index_path = fs::path(find_string_value(text, "archive_index_path"));
    job.archive_basename_index_path = fs::path(find_string_value(text, "archive_basename_index_path"));
    job.schema_version = static_cast<int>(std::max<long long>(1, find_int_value(text, "schema_version", 4)));
    const std::string entry_object = find_object_value(text, "entry");
    job.entry = parse_archive_entry_ref(entry_object.empty() ? text : entry_object);
    const std::string companion_object = find_object_value(text, "companion_entry");
    job.companion_entry = parse_archive_entry_ref(companion_object);
    bool dependency_entries_truncated = false;
    for (const std::string& dependency_object : find_object_array_values(
             text,
             "archive_dependency_entries",
             4096,
             dependency_entries_truncated)) {
        job.archive_dependency_entries.push_back(parse_archive_entry_ref(dependency_object));
    }
    job.archive_dependency_entries_complete = find_bool_value(
        text,
        "archive_dependency_entries_complete",
        false);
    if (job.archive_dependency_entries_complete && dependency_entries_truncated) {
        throw std::runtime_error("archive dependency entries exceeded the 4,096-entry safety bound");
    }
    job.path = job.entry.path;
    job.extension = job.entry.extension.empty() ? basename_extension(job.path) : job.entry.extension;
    job.paz_file = job.entry.paz_file;
    job.offset = job.entry.offset;
    job.comp_size = job.entry.comp_size;
    job.orig_size = job.entry.orig_size;
    job.flags = job.entry.flags;
    const std::string render_settings = find_object_value(text, "render_settings");
    if (!render_settings.empty()) {
        const std::string native_visible_mode = find_string_value(render_settings, "visible_texture_mode");
        if (!native_visible_mode.empty()) job.visible_texture_mode = normalize_visible_texture_mode(native_visible_mode);
        const std::string diagnostic_mode = lower_copy(find_string_value(render_settings, "render_diagnostic_mode"));
        if (!diagnostic_mode.empty()) job.render_diagnostic_mode = diagnostic_mode;
        const std::string d3d11_view_mode = lower_copy(find_string_value(render_settings, "d3d11_view_mode"));
        if (!d3d11_view_mode.empty()) job.d3d11_view_mode = d3d11_view_mode;
        const std::string d3d11_normal_y_mode = lower_copy(find_string_value(render_settings, "d3d11_normal_y_mode"));
        if (!d3d11_normal_y_mode.empty()) job.d3d11_normal_y_mode = d3d11_normal_y_mode;
        const std::string d3d11_texture_address_mode = lower_copy(find_string_value(render_settings, "d3d11_texture_address_mode"));
        if (d3d11_texture_address_mode == "clamp") job.d3d11_texture_address_mode = "clamp";
        else if (d3d11_texture_address_mode == "wrap") job.d3d11_texture_address_mode = "wrap";
        job.use_textures = find_bool_value(render_settings, "use_textures_by_default", job.use_textures);
        job.high_quality_textures = find_bool_value(render_settings, "high_quality_by_default", job.high_quality_textures);
        job.disable_all_support_maps = find_bool_value(render_settings, "disable_all_support_maps", job.disable_all_support_maps);
        job.disable_normal_map = find_bool_value(render_settings, "disable_normal_map", job.disable_normal_map);
        job.disable_material_map = find_bool_value(render_settings, "disable_material_map", job.disable_material_map);
        job.disable_height_map = find_bool_value(render_settings, "disable_height_map", job.disable_height_map);
        job.flip_texture_v = find_bool_value(render_settings, "flip_texture_v", job.flip_texture_v);
        job.normal_strength_cap = std::clamp(find_float_value(render_settings, "normal_strength_cap", job.normal_strength_cap), 0.0f, 2.0f);
        job.height_effect_max = std::clamp(find_float_value(render_settings, "height_effect_max", job.height_effect_max), 0.0f, 1.5f);
        job.max_anisotropy = static_cast<int>(std::clamp<long long>(find_int_value(render_settings, "max_anisotropy", job.max_anisotropy), 1, 16));
        job.d3d11_mip_lod_bias = std::clamp(find_float_value(render_settings, "d3d11_mip_lod_bias", job.d3d11_mip_lod_bias), -2.0f, 1.0f);
        job.d3d11_cull_back_faces = find_bool_value(render_settings, "d3d11_cull_back_faces", job.d3d11_cull_back_faces);
        job.d3d11_light_azimuth_degrees = std::clamp(find_float_value(render_settings, "d3d11_light_azimuth_degrees", job.d3d11_light_azimuth_degrees), -180.0f, 180.0f);
        job.d3d11_light_elevation_degrees = std::clamp(find_float_value(render_settings, "d3d11_light_elevation_degrees", job.d3d11_light_elevation_degrees), -80.0f, 80.0f);
        job.d3d11_ao_strength = std::clamp(find_float_value(render_settings, "d3d11_ao_strength", job.d3d11_ao_strength), 0.0f, 2.0f);
        job.d3d11_roughness_bias = std::clamp(find_float_value(render_settings, "d3d11_roughness_bias", job.d3d11_roughness_bias), -0.5f, 0.5f);
        job.d3d11_metalness_scale = std::clamp(find_float_value(render_settings, "d3d11_metalness_scale", job.d3d11_metalness_scale), 0.0f, 2.0f);
        job.d3d11_environment_strength = std::clamp(find_float_value(render_settings, "d3d11_environment_strength", job.d3d11_environment_strength), 0.0f, 2.0f);
        job.d3d11_emissive_gain = std::clamp(find_float_value(render_settings, "d3d11_emissive_gain", job.d3d11_emissive_gain), 0.0f, 4.0f);
        job.d3d11_tone_exposure = std::clamp(find_float_value(render_settings, "d3d11_tone_exposure", job.d3d11_tone_exposure), 0.25f, 2.0f);
        job.d3d11_tone_contrast = std::clamp(find_float_value(render_settings, "d3d11_tone_contrast", job.d3d11_tone_contrast), 0.50f, 1.75f);
        job.d3d11_tone_gamma = std::clamp(find_float_value(render_settings, "d3d11_tone_gamma", job.d3d11_tone_gamma), 0.50f, 2.20f);
        job.ambient_strength = std::clamp(find_float_value(render_settings, "ambient_strength", job.ambient_strength), 0.05f, 1.2f);
        job.diffuse_wrap_bias = std::clamp(find_float_value(render_settings, "diffuse_wrap_bias", job.diffuse_wrap_bias), 0.0f, 1.0f);
        job.diffuse_light_scale = std::clamp(find_float_value(render_settings, "diffuse_light_scale", job.diffuse_light_scale), 0.05f, 1.5f);
        job.specular_base = std::clamp(find_float_value(render_settings, "specular_base", job.specular_base), 0.0f, 0.5f);
        job.specular_max = std::clamp(find_float_value(render_settings, "specular_max", job.specular_max), job.specular_base, 1.0f);
        job.shininess_min = std::clamp(find_float_value(render_settings, "shininess_min", job.shininess_min), 1.0f, 128.0f);
        job.shininess_max = std::clamp(find_float_value(render_settings, "shininess_max", job.shininess_max), job.shininess_min, 256.0f);
        job.orbit_sensitivity = std::clamp(find_float_value(render_settings, "orbit_sensitivity", job.orbit_sensitivity), 0.001f, 8.0f);
        job.pan_sensitivity = std::clamp(find_float_value(render_settings, "pan_sensitivity", job.pan_sensitivity), 0.001f, 8.0f);
        job.invert_orbit_x = find_bool_value(render_settings, "invert_orbit_x", job.invert_orbit_x);
        job.invert_orbit_y = find_bool_value(render_settings, "invert_orbit_y", job.invert_orbit_y);
        job.invert_pan_x = find_bool_value(render_settings, "invert_pan_x", job.invert_pan_x);
        job.invert_pan_y = find_bool_value(render_settings, "invert_pan_y", job.invert_pan_y);
    }
    if (job.output_root.empty()) job.output_root = fs::temp_directory_path() / "cdmw_preview_core_package";
    if (job.cache_root.empty()) job.cache_root = fs::temp_directory_path() / "cdmw_preview_core_cache";
    return job;
}
