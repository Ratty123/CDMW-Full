#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

namespace {

constexpr int kNativePackageSchemaVersion = 8;
constexpr int kNativeMaterialGraphVersion = 3;
constexpr int kNativeMaterialSemanticsVersion = 3;

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
    int schema_version = 4;
    ArchiveEntryRef entry;
    ArchiveEntryRef companion_entry;
    bool use_textures = true;
    bool high_quality_textures = true;
    bool disable_all_support_maps = false;
    bool disable_normal_map = false;
    bool disable_material_map = false;
    bool disable_height_map = false;
    float normal_strength_cap = 1.0f;
    float height_effect_max = 0.35f;
    int max_anisotropy = 16;
    float ambient_strength = 0.55f;
    float diffuse_light_scale = 0.65f;
    float specular_base = 0.05f;
    float specular_max = 0.18f;
    float shininess_min = 28.0f;
    float shininess_max = 72.0f;
    float orbit_sensitivity = 0.22f;
    float pan_sensitivity = 0.60f;
    bool invert_orbit_x = false;
    bool invert_orbit_y = false;
    bool invert_pan_x = false;
    bool invert_pan_y = false;
    std::string visible_texture_mode = "mesh_base_first";
};

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
    std::vector<Vec3> positions;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    std::vector<std::uint32_t> indices;
    std::vector<std::int32_t> source_vertex_indices;
    int source_submesh_index = -1;
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
    float layer_weight = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
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
    job.schema_version = static_cast<int>(std::max<long long>(1, find_int_value(text, "schema_version", 4)));
    const std::string entry_object = find_object_value(text, "entry");
    job.entry = parse_archive_entry_ref(entry_object.empty() ? text : entry_object);
    const std::string companion_object = find_object_value(text, "companion_entry");
    job.companion_entry = parse_archive_entry_ref(companion_object);
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
        job.use_textures = find_bool_value(render_settings, "use_textures_by_default", job.use_textures);
        job.high_quality_textures = find_bool_value(render_settings, "high_quality_by_default", job.high_quality_textures);
        job.disable_all_support_maps = find_bool_value(render_settings, "disable_all_support_maps", job.disable_all_support_maps);
        job.disable_normal_map = find_bool_value(render_settings, "disable_normal_map", job.disable_normal_map);
        job.disable_material_map = find_bool_value(render_settings, "disable_material_map", job.disable_material_map);
        job.disable_height_map = find_bool_value(render_settings, "disable_height_map", job.disable_height_map);
        job.normal_strength_cap = std::clamp(find_float_value(render_settings, "normal_strength_cap", job.normal_strength_cap), 0.0f, 2.0f);
        job.height_effect_max = std::clamp(find_float_value(render_settings, "height_effect_max", job.height_effect_max), 0.0f, 1.5f);
        job.max_anisotropy = static_cast<int>(std::clamp<long long>(find_int_value(render_settings, "max_anisotropy", job.max_anisotropy), 1, 16));
        job.ambient_strength = std::clamp(find_float_value(render_settings, "ambient_strength", job.ambient_strength), 0.05f, 1.2f);
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

static std::vector<char> read_archive_ref_raw_bytes(const ArchiveEntryRef& entry) {
    if (entry.paz_file.empty()) {
        throw std::runtime_error("job has no paz_file");
    }
    if (entry.comp_size == 0) {
        return {};
    }
    std::ifstream in(entry.paz_file, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open PAZ file " + entry.paz_file.string());
    }
    in.seekg(0, std::ios::end);
    const auto end_pos = in.tellg();
    if (end_pos < 0) {
        throw std::runtime_error("could not determine PAZ file size");
    }
    const std::uint64_t file_size = static_cast<std::uint64_t>(end_pos);
    if (entry.offset > file_size || entry.comp_size > file_size || entry.offset + entry.comp_size > file_size) {
        throw std::runtime_error("archive entry byte range is outside the PAZ file");
    }
    in.seekg(static_cast<std::streamoff>(entry.offset), std::ios::beg);
    std::vector<char> data(static_cast<size_t>(entry.comp_size));
    if (!data.empty()) {
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) {
            throw std::runtime_error("short read from PAZ file");
        }
    }
    return data;
}

static std::vector<char> read_entry_raw_bytes(const EntryJob& job) {
    return read_archive_ref_raw_bytes(job.entry.path.empty() ? ArchiveEntryRef{
        job.path,
        basename_from_path(job.path),
        job.extension,
        fs::path(),
        job.paz_file,
        job.offset,
        job.comp_size,
        job.orig_size,
        job.flags,
        0,
    } : job.entry);
}

static std::vector<char> crypt_chacha20_filename(const std::vector<char>& data, const std::string& filename);

static std::vector<char> lz4_decompress_block(const std::vector<char>& input, size_t output_size) {
    std::vector<char> output(output_size);
    size_t ip = 0;
    size_t op = 0;
    while (ip < input.size()) {
        const unsigned char token = static_cast<unsigned char>(input[ip++]);
        size_t literal_len = token >> 4;
        if (literal_len == 15) {
            unsigned char s = 255;
            while (ip < input.size() && s == 255) {
                s = static_cast<unsigned char>(input[ip++]);
                literal_len += s;
            }
        }
        if (ip + literal_len > input.size() || op + literal_len > output.size()) {
            throw std::runtime_error("LZ4 literal run is outside buffer");
        }
        if (literal_len > 0) {
            std::memcpy(output.data() + op, input.data() + ip, literal_len);
            ip += literal_len;
            op += literal_len;
        }
        if (ip >= input.size()) break;
        if (ip + 2 > input.size()) throw std::runtime_error("LZ4 match offset is truncated");
        const size_t match_offset = static_cast<unsigned char>(input[ip]) | (static_cast<size_t>(static_cast<unsigned char>(input[ip + 1])) << 8);
        ip += 2;
        if (match_offset == 0 || match_offset > op) throw std::runtime_error("LZ4 match offset is invalid");
        size_t match_len = token & 0x0Fu;
        if (match_len == 15) {
            unsigned char s = 255;
            while (ip < input.size() && s == 255) {
                s = static_cast<unsigned char>(input[ip++]);
                match_len += s;
            }
        }
        match_len += 4;
        if (op + match_len > output.size()) throw std::runtime_error("LZ4 match run is outside output buffer");
        for (size_t i = 0; i < match_len; ++i) {
            output[op + i] = output[op - match_offset + i];
        }
        op += match_len;
    }
    if (op != output.size()) {
        output.resize(op);
    }
    return output;
}

static std::vector<char> maybe_decompress_partial_par(const ArchiveEntryRef& entry, const std::vector<char>& data) {
    if (entry.compression_type() != 1 || data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") {
        return {};
    }
    struct Slot {
        std::uint32_t comp_size = 0;
        std::uint32_t decomp_size = 0;
        size_t offset = 0;
    };
    std::vector<Slot> slots;
    size_t file_offset = 0x50;
    size_t rebuilt_size = 0x50;
    bool saw_compressed = false;
    for (int slot = 0; slot < 8; ++slot) {
        const size_t slot_offset = 0x10u + static_cast<size_t>(slot) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_offset);
        const std::uint32_t decomp_size = read_u32(data, slot_offset + 4);
        if (decomp_size == 0) continue;
        const std::uint32_t chunk_size = comp_size > 0 ? comp_size : decomp_size;
        if (chunk_size == 0 || file_offset + chunk_size > data.size()) return {};
        if (decomp_size > entry.orig_size || rebuilt_size + decomp_size > entry.orig_size) return {};
        slots.push_back(Slot{comp_size, decomp_size, file_offset});
        file_offset += chunk_size;
        rebuilt_size += decomp_size;
        if (comp_size > 0) saw_compressed = true;
    }
    if (!saw_compressed || file_offset != data.size() || rebuilt_size != entry.orig_size) return {};
    std::vector<char> rebuilt(data.begin(), data.begin() + 0x50);
    for (const Slot& slot : slots) {
        const size_t chunk_size = slot.comp_size > 0 ? slot.comp_size : slot.decomp_size;
        std::vector<char> chunk(data.begin() + static_cast<std::ptrdiff_t>(slot.offset), data.begin() + static_cast<std::ptrdiff_t>(slot.offset + chunk_size));
        if (slot.comp_size > 0) {
            chunk = lz4_decompress_block(chunk, slot.decomp_size);
            if (chunk.size() != slot.decomp_size) return {};
        }
        rebuilt.insert(rebuilt.end(), chunk.begin(), chunk.end());
    }
    if (rebuilt.size() != entry.orig_size) return {};
    for (int slot = 0; slot < 8; ++slot) {
        const size_t off = 0x10u + static_cast<size_t>(slot) * 8u;
        if (off + 4 <= rebuilt.size()) {
            rebuilt[off + 0] = 0;
            rebuilt[off + 1] = 0;
            rebuilt[off + 2] = 0;
            rebuilt[off + 3] = 0;
        }
    }
    return rebuilt;
}

static std::vector<char> decode_archive_ref_bytes(const ArchiveEntryRef& entry, const std::vector<char>& raw) {
    std::vector<char> data = raw;
    if (entry.encrypted()) {
        if (entry.encryption_type() != 3) {
            throw std::runtime_error("unsupported archive encryption type " + std::to_string(entry.encryption_type()));
        }
        data = crypt_chacha20_filename(data, entry.basename.empty() ? basename_from_path(entry.path) : entry.basename);
    }
    if (!entry.compressed()) return data;
    if (entry.compression_type() == 2) {
        return lz4_decompress_block(data, static_cast<size_t>(entry.orig_size));
    }
    if (entry.compression_type() == 1) {
        std::vector<char> partial_par = maybe_decompress_partial_par(entry, data);
        if (!partial_par.empty()) return partial_par;
        if (entry.extension == ".dds" && data.size() >= 4 && std::string(data.data(), data.data() + 4) == "DDS " && data.size() >= 128) {
            std::vector<char> padded = data;
            padded.resize(static_cast<size_t>(entry.orig_size), 0);
            return padded;
        }
        return data;
    }
    if (entry.extension == ".dds" && data.size() >= 4 && std::string(data.data(), data.data() + 4) == "DDS " && data.size() >= 128) {
        std::vector<char> padded = data;
        padded.resize(static_cast<size_t>(entry.orig_size), 0);
        return padded;
    }
    throw std::runtime_error("unsupported archive compression type " + std::to_string(entry.compression_type()));
}

static std::string archive_ref_identity(const ArchiveEntryRef& entry) {
    return entry.pamt_path.string() + "|" + entry.paz_file.string() + "|" + entry.path + "|" +
        std::to_string(entry.offset) + "|" + std::to_string(entry.comp_size) + "|" +
        std::to_string(entry.orig_size) + "|" + std::to_string(entry.flags) + "|" +
        std::to_string(entry.paz_index);
}

struct DecodedEntryCacheValue {
    std::vector<char> bytes;
    size_t last_used = 0;
};

static std::unordered_map<std::string, DecodedEntryCacheValue> g_decoded_entry_cache;
static size_t g_decoded_entry_cache_bytes = 0;
static size_t g_decoded_entry_cache_clock = 0;
static std::uint64_t g_decoded_entry_cache_hits = 0;
static std::uint64_t g_decoded_entry_cache_misses = 0;
static std::uint64_t g_decoded_entry_cache_evictions = 0;
static std::uint64_t g_service_job_count = 0;
static constexpr size_t kDecodedEntryCacheMaxEntries = 512;
static constexpr size_t kDecodedEntryCacheMaxBytes = 256ull * 1024ull * 1024ull;
static constexpr size_t kDecodedEntryCacheMaxSingleBytes = 64ull * 1024ull * 1024ull;
static constexpr size_t kDecodedEntryCacheRecycleBytes = 192ull * 1024ull * 1024ull;
static constexpr std::uint64_t kServiceMaxJobs = 32;
static constexpr unsigned long long kServicePrivateRecycleBytes = 768ull * 1024ull * 1024ull;

static size_t decoded_entry_cache_entries() {
    return g_decoded_entry_cache.size();
}

static size_t decoded_entry_cache_bytes() {
    return g_decoded_entry_cache_bytes;
}

static std::uint64_t decoded_entry_cache_hits() {
    return g_decoded_entry_cache_hits;
}

static std::uint64_t decoded_entry_cache_misses() {
    return g_decoded_entry_cache_misses;
}

static std::uint64_t decoded_entry_cache_evictions() {
    return g_decoded_entry_cache_evictions;
}

static std::string service_recycle_reason(const cdmw_native_diag::ProcessMemorySnapshot& memory) {
    if (g_service_job_count >= kServiceMaxJobs) {
        return "job_count";
    }
    if (decoded_entry_cache_bytes() > kDecodedEntryCacheRecycleBytes) {
        return "decoded_cache_bytes";
    }
    if (memory.ok && memory.private_bytes > kServicePrivateRecycleBytes) {
        return "process_private_bytes";
    }
    return "";
}

static void prune_decoded_entry_cache() {
    while (
        g_decoded_entry_cache.size() > kDecodedEntryCacheMaxEntries ||
        g_decoded_entry_cache_bytes > kDecodedEntryCacheMaxBytes
    ) {
        auto oldest = g_decoded_entry_cache.end();
        size_t oldest_tick = std::numeric_limits<size_t>::max();
        for (auto it = g_decoded_entry_cache.begin(); it != g_decoded_entry_cache.end(); ++it) {
            if (it->second.last_used < oldest_tick) {
                oldest_tick = it->second.last_used;
                oldest = it;
            }
        }
        if (oldest == g_decoded_entry_cache.end()) break;
        g_decoded_entry_cache_bytes -= oldest->second.bytes.size();
        g_decoded_entry_cache.erase(oldest);
        ++g_decoded_entry_cache_evictions;
    }
}

static std::vector<char> read_archive_ref_decoded_bytes(const ArchiveEntryRef& entry) {
    const std::string key = archive_ref_identity(entry);
    auto found = g_decoded_entry_cache.find(key);
    if (found != g_decoded_entry_cache.end()) {
        ++g_decoded_entry_cache_hits;
        found->second.last_used = ++g_decoded_entry_cache_clock;
        return found->second.bytes;
    }
    ++g_decoded_entry_cache_misses;
    std::vector<char> decoded = decode_archive_ref_bytes(entry, read_archive_ref_raw_bytes(entry));
    if (decoded.size() <= kDecodedEntryCacheMaxSingleBytes) {
        g_decoded_entry_cache_bytes += decoded.size();
        g_decoded_entry_cache.emplace(key, DecodedEntryCacheValue{decoded, ++g_decoded_entry_cache_clock});
        prune_decoded_entry_cache();
    }
    return decoded;
}

static std::vector<char> read_entry_decoded_bytes(const EntryJob& job) {
    if (!job.entry.path.empty()) return read_archive_ref_decoded_bytes(job.entry);
    std::vector<char> raw = read_entry_raw_bytes(job);
    ArchiveEntryRef ref;
    ref.path = job.path;
    ref.extension = job.extension;
    ref.paz_file = job.paz_file;
    ref.offset = job.offset;
    ref.comp_size = job.comp_size;
    ref.orig_size = job.orig_size;
    ref.flags = job.flags;
    return decode_archive_ref_bytes(ref, raw);
}

static void write_binary(const fs::path& path, const std::vector<char>& data) {
    if (!path.parent_path().empty()) {
        fs::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("could not write " + path.string());
    }
    if (!data.empty()) {
        out.write(data.data(), static_cast<std::streamsize>(data.size()));
    }
}

static std::string safe_filename(std::string value) {
    if (value.empty()) value = "texture";
    for (char& ch : value) {
        const unsigned char u = static_cast<unsigned char>(ch);
        if (!(std::isalnum(u) || ch == '.' || ch == '_' || ch == '-')) {
            ch = '_';
        }
    }
    return value;
}

static std::uint64_t fnv1a64(const std::string& text) {
    std::uint64_t hash = 1469598103934665603ull;
    for (unsigned char ch : text) {
        hash ^= static_cast<std::uint64_t>(ch);
        hash *= 1099511628211ull;
    }
    return hash;
}

static std::string hex64(std::uint64_t value) {
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << value;
    return out.str();
}

static std::uint32_t rot32(std::uint32_t value, int shift) {
    return (value << shift) | (value >> (32 - shift));
}

static std::uint32_t lookup3_finalize_c(std::uint32_t a, std::uint32_t b, std::uint32_t c) {
    c = (c ^ b) - rot32(b, 14);
    a = (a ^ c) - rot32(c, 11);
    b = (b ^ a) - rot32(a, 25);
    c = (c ^ b) - rot32(b, 16);
    a = (a ^ c) - rot32(c, 4);
    b = (b ^ a) - rot32(a, 14);
    c = (c ^ b) - rot32(b, 24);
    return c;
}

static std::uint32_t read_u32_padded(const std::vector<unsigned char>& data, size_t offset) {
    std::uint32_t value = 0;
    for (size_t i = 0; i < 4; ++i) {
        if (offset + i < data.size()) {
            value |= static_cast<std::uint32_t>(data[offset + i]) << (i * 8);
        }
    }
    return value;
}

static std::uint32_t hashlittle_bytes(const std::vector<unsigned char>& data, std::uint32_t initval) {
    size_t length = data.size();
    size_t remaining = length;
    std::uint32_t a = 0xDEADBEEFu + static_cast<std::uint32_t>(length) + initval;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    while (remaining > 12) {
        a += read_u32_padded(data, offset);
        b += read_u32_padded(data, offset + 4);
        c += read_u32_padded(data, offset + 8);
        a -= c; a ^= rot32(c, 4); c += b;
        b -= a; b ^= rot32(a, 6); a += c;
        c -= b; c ^= rot32(b, 8); b += a;
        a -= c; a ^= rot32(c, 16); c += b;
        b -= a; b ^= rot32(a, 19); a += c;
        c -= b; c ^= rot32(b, 4); b += a;
        offset += 12;
        remaining -= 12;
    }
    if (remaining >= 12) {
        c += read_u32_padded(data, offset + 8);
    } else if (remaining >= 9) {
        c += read_u32_padded(data, offset + 8) & (0xFFFFFFFFu >> (8u * (12u - static_cast<unsigned int>(remaining))));
    }
    if (remaining >= 8) {
        b += read_u32_padded(data, offset + 4);
    } else if (remaining >= 5) {
        b += read_u32_padded(data, offset + 4) & (0xFFFFFFFFu >> (8u * (8u - static_cast<unsigned int>(remaining))));
    }
    if (remaining >= 4) {
        a += read_u32_padded(data, offset);
    } else if (remaining >= 1) {
        a += read_u32_padded(data, offset) & (0xFFFFFFFFu >> (8u * (4u - static_cast<unsigned int>(remaining))));
    } else {
        return c;
    }
    return lookup3_finalize_c(a, b, c);
}

static void chacha_quarter_round(std::uint32_t& a, std::uint32_t& b, std::uint32_t& c, std::uint32_t& d) {
    a += b; d ^= a; d = rot32(d, 16);
    c += d; b ^= c; b = rot32(b, 12);
    a += b; d ^= a; d = rot32(d, 8);
    c += d; b ^= c; b = rot32(b, 7);
}

static void chacha20_block(const std::array<std::uint32_t, 16>& state, std::array<unsigned char, 64>& out) {
    std::array<std::uint32_t, 16> working = state;
    for (int i = 0; i < 10; ++i) {
        chacha_quarter_round(working[0], working[4], working[8], working[12]);
        chacha_quarter_round(working[1], working[5], working[9], working[13]);
        chacha_quarter_round(working[2], working[6], working[10], working[14]);
        chacha_quarter_round(working[3], working[7], working[11], working[15]);
        chacha_quarter_round(working[0], working[5], working[10], working[15]);
        chacha_quarter_round(working[1], working[6], working[11], working[12]);
        chacha_quarter_round(working[2], working[7], working[8], working[13]);
        chacha_quarter_round(working[3], working[4], working[9], working[14]);
    }
    for (size_t i = 0; i < 16; ++i) {
        working[i] += state[i];
        out[i * 4 + 0] = static_cast<unsigned char>((working[i] >> 0) & 0xFF);
        out[i * 4 + 1] = static_cast<unsigned char>((working[i] >> 8) & 0xFF);
        out[i * 4 + 2] = static_cast<unsigned char>((working[i] >> 16) & 0xFF);
        out[i * 4 + 3] = static_cast<unsigned char>((working[i] >> 24) & 0xFF);
    }
}

static std::vector<char> crypt_chacha20_filename(const std::vector<char>& data, const std::string& filename) {
    std::string base = lower_copy(basename_from_path(filename));
    std::vector<unsigned char> base_bytes(base.begin(), base.end());
    const std::uint32_t seed = hashlittle_bytes(base_bytes, 0x000C5EDEu);
    const std::uint32_t key_base = seed ^ 0x60616263u;
    const std::array<std::uint32_t, 8> deltas = {
        0x00000000u, 0x0A0A0A0Au, 0x0C0C0C0Cu, 0x06060606u,
        0x0E0E0E0Eu, 0x0A0A0A0Au, 0x06060606u, 0x02020202u,
    };
    std::array<std::uint32_t, 16> state = {
        0x61707865u, 0x3320646Eu, 0x79622D32u, 0x6B206574u,
        key_base ^ deltas[0], key_base ^ deltas[1], key_base ^ deltas[2], key_base ^ deltas[3],
        key_base ^ deltas[4], key_base ^ deltas[5], key_base ^ deltas[6], key_base ^ deltas[7],
        seed, seed, seed, seed,
    };
    std::vector<char> out(data.size());
    size_t offset = 0;
    while (offset < data.size()) {
        std::array<unsigned char, 64> block{};
        chacha20_block(state, block);
        const size_t n = std::min<size_t>(64, data.size() - offset);
        for (size_t i = 0; i < n; ++i) {
            out[offset + i] = static_cast<char>(static_cast<unsigned char>(data[offset + i]) ^ block[i]);
        }
        ++state[12];
        if (state[12] == 0) ++state[13];
        offset += n;
    }
    return out;
}

class VfsPathResolver {
public:
    explicit VfsPathResolver(const std::vector<char>& name_block) : name_block_(name_block) {
        cache_[0xFFFFFFFFu] = "";
    }

    std::string get_full_path(std::uint32_t offset) {
        if (offset == 0xFFFFFFFFu || offset >= name_block_.size()) return "";
        auto cached = cache_.find(offset);
        if (cached != cache_.end()) return cached->second;
        std::vector<std::pair<std::uint32_t, std::string>> parts;
        std::uint32_t current = offset;
        std::string base;
        std::set<std::uint32_t> seen;
        while (current != 0xFFFFFFFFu) {
            if (!seen.insert(current).second) break;
            auto hit = cache_.find(current);
            if (hit != cache_.end()) {
                base = hit->second;
                break;
            }
            if (static_cast<size_t>(current) + 5 > name_block_.size()) break;
            const std::uint32_t parent = read_u32(name_block_, current);
            const std::uint8_t part_len = static_cast<std::uint8_t>(name_block_[current + 4]);
            if (static_cast<size_t>(current) + 5 + part_len > name_block_.size()) break;
            std::string part(name_block_.data() + current + 5, name_block_.data() + current + 5 + part_len);
            parts.emplace_back(current, part);
            current = parent;
            if (parts.size() > 255) break;
        }
        std::string built = base;
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
            built += it->second;
            if (cache_.size() < 200000) {
                cache_[it->first] = built;
            }
        }
        return built;
    }

private:
    const std::vector<char>& name_block_;
    std::unordered_map<std::uint32_t, std::string> cache_;
};

struct PamtIndex {
    fs::path pamt_path;
    std::unordered_map<std::string, std::vector<ArchiveEntryRef>> by_basename;
    std::unordered_map<std::string, ArchiveEntryRef> by_path;
    std::vector<ArchiveEntryRef> material_sidecars;
    size_t entry_count = 0;
};

static PamtIndex parse_pamt_index(const fs::path& pamt_path) {
    if (pamt_path.empty()) {
        throw std::runtime_error("job has no pamt_path");
    }
    std::ifstream in(pamt_path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open PAMT file " + pamt_path.string());
    }
    in.seekg(0, std::ios::end);
    const auto size_pos = in.tellg();
    if (size_pos < 0) throw std::runtime_error("could not determine PAMT size");
    in.seekg(0, std::ios::beg);
    std::vector<char> data(static_cast<size_t>(size_pos));
    if (!data.empty()) {
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) {
            throw std::runtime_error("short read from PAMT file");
        }
    }
    if (data.size() < 12) throw std::runtime_error("PAMT file is too small");
    size_t off = 0;
    (void)read_u32(data, off);
    off += 4;
    const std::uint32_t paz_count = read_u32(data, off);
    off += 8;
    off += static_cast<size_t>(paz_count) * 12u;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT directory block length is truncated");
    const std::uint32_t dir_block_size = read_u32(data, off);
    off += 4;
    if (off + dir_block_size > data.size()) throw std::runtime_error("PAMT directory block is truncated");
    std::vector<char> directory_data(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + dir_block_size));
    off += dir_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT filename block length is truncated");
    const std::uint32_t file_name_block_size = read_u32(data, off);
    off += 4;
    if (off + file_name_block_size > data.size()) throw std::runtime_error("PAMT filename block is truncated");
    std::vector<char> file_names(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + file_name_block_size));
    off += file_name_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT folder count is truncated");
    const std::uint32_t folder_count = read_u32(data, off);
    off += 4;
    const size_t folder_table_offset = off;
    const size_t folder_table_size = static_cast<size_t>(folder_count) * 16u;
    if (off + folder_table_size > data.size()) throw std::runtime_error("PAMT folder table is truncated");
    off += folder_table_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT file count is truncated");
    const std::uint32_t file_count = read_u32(data, off);
    off += 4;
    const size_t file_table_offset = off;
    const size_t file_record_size = 20u;
    if (off + static_cast<size_t>(file_count) * file_record_size > data.size()) {
        throw std::runtime_error("PAMT file table is truncated");
    }

    VfsPathResolver file_resolver(file_names);
    VfsPathResolver dir_resolver(directory_data);
    struct FolderRange {
        std::uint32_t start = 0;
        std::uint32_t end = 0;
        std::string path;
    };
    std::vector<FolderRange> folder_ranges;
    folder_ranges.reserve(folder_count);
    for (std::uint32_t i = 0; i < folder_count; ++i) {
        const size_t base = folder_table_offset + static_cast<size_t>(i) * 16u;
        const std::uint32_t name_offset = read_u32(data, base + 4);
        const std::uint32_t start = read_u32(data, base + 8);
        const std::uint32_t count = read_u32(data, base + 12);
        if (count == 0) continue;
        std::string folder = dir_resolver.get_full_path(name_offset);
        std::replace(folder.begin(), folder.end(), '\\', '/');
        while (!folder.empty() && folder.front() == '/') folder.erase(folder.begin());
        while (!folder.empty() && folder.back() == '/') folder.pop_back();
        folder_ranges.push_back(FolderRange{start, start + count, folder});
    }
    std::sort(folder_ranges.begin(), folder_ranges.end(), [](const FolderRange& a, const FolderRange& b) {
        return a.start < b.start;
    });

    PamtIndex index;
    index.pamt_path = pamt_path;
    index.entry_count = file_count;
    size_t folder_cursor = 0;
    for (std::uint32_t entry_index = 0; entry_index < file_count; ++entry_index) {
        const size_t base = file_table_offset + static_cast<size_t>(entry_index) * file_record_size;
        const std::uint32_t name_offset = read_u32(data, base);
        const std::uint32_t paz_offset = read_u32(data, base + 4);
        const std::uint32_t comp_size = read_u32(data, base + 8);
        const std::uint32_t orig_size = read_u32(data, base + 12);
        const std::uint16_t paz_index = read_u16(data, base + 16);
        const std::uint16_t flags = read_u16(data, base + 18);
        std::string relative = file_resolver.get_full_path(name_offset);
        std::replace(relative.begin(), relative.end(), '\\', '/');
        while (!relative.empty() && relative.front() == '/') relative.erase(relative.begin());
        while (folder_cursor < folder_ranges.size() && entry_index >= folder_ranges[folder_cursor].end) {
            ++folder_cursor;
        }
        std::string folder;
        if (folder_cursor < folder_ranges.size()) {
            const FolderRange& range = folder_ranges[folder_cursor];
            if (entry_index >= range.start && entry_index < range.end) {
                folder = range.path;
            }
        }
        const std::string full_path = folder.empty() ? relative : (folder + "/" + relative);
        ArchiveEntryRef ref;
        ref.path = full_path;
        ref.basename = basename_from_path(full_path);
        ref.extension = extension_from_path(full_path);
        ref.pamt_path = pamt_path;
        ref.paz_index = paz_index;
        ref.paz_file = pamt_path.parent_path() / (std::to_string(paz_index) + ".paz");
        ref.offset = paz_offset;
        ref.comp_size = comp_size;
        ref.orig_size = orig_size;
        ref.flags = flags;
        index.by_basename[lower_copy(ref.basename)].push_back(ref);
        index.by_path[lower_copy(full_path)] = ref;
        if (
            ref.extension == ".pami" ||
            ref.extension == ".pac_xml" ||
            ref.extension == ".pam_xml" ||
            ref.extension == ".pamlod_xml" ||
            ref.extension == ".material" ||
            ref.extension == ".technique" ||
            ref.extension == ".prefab" ||
            ref.extension == ".prefabdata_xml" ||
            ref.extension == ".meshinfo"
        ) {
            index.material_sidecars.push_back(ref);
        }
    }
    return index;
}

static const PamtIndex& cached_pamt_index(const fs::path& pamt_path) {
    static std::map<std::string, PamtIndex> cache;
    const std::string key = fs::absolute(pamt_path).string();
    auto it = cache.find(key);
    if (it == cache.end()) {
        it = cache.emplace(key, parse_pamt_index(pamt_path)).first;
    }
    return it->second;
}

std::string fourcc_from_bytes(const std::vector<char>& data) {
    if (data.size() < 4) return "";
    std::string value(data.data(), data.data() + 4);
    for (char& ch : value) {
        if (static_cast<unsigned char>(ch) < 0x20 || static_cast<unsigned char>(ch) > 0x7e) ch = '.';
    }
    return value;
}

static float vec_dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

static Vec3 vec_cross(const Vec3& a, const Vec3& b) {
    return Vec3{
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

static Vec3 vec_add(const Vec3& a, const Vec3& b) {
    return Vec3{a.x + b.x, a.y + b.y, a.z + b.z};
}

static Vec3 vec_sub(const Vec3& a, const Vec3& b) {
    return Vec3{a.x - b.x, a.y - b.y, a.z - b.z};
}

static Vec3 vec_mul(const Vec3& value, float scale) {
    return Vec3{value.x * scale, value.y * scale, value.z * scale};
}

static Vec3 vec_normalize(const Vec3& value, const Vec3& fallback = Vec3{0.0f, 1.0f, 0.0f}) {
    const float len2 = vec_dot(value, value);
    if (len2 <= 1.0e-12f || !std::isfinite(len2)) return fallback;
    const float inv = 1.0f / std::sqrt(len2);
    return Vec3{value.x * inv, value.y * inv, value.z * inv};
}

static std::vector<ParSection> parse_par_sections(const std::vector<char>& data) {
    std::vector<ParSection> sections;
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") return sections;
    std::uint32_t offset = 0x50;
    for (int i = 0; i < 8; ++i) {
        const size_t slot_off = 0x10u + static_cast<size_t>(i) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_off);
        const std::uint32_t decomp_size = read_u32(data, slot_off + 4);
        const std::uint32_t stored_size = comp_size > 0 ? comp_size : decomp_size;
        if (decomp_size == 0) continue;
        if (offset + stored_size > data.size()) return {};
        if (comp_size > 0 && comp_size < decomp_size) {
            // A compressed PAR section needs LZ4 reconstruction. Keep this
            // path conservative and report unsupported until native recovery is proven.
            return {};
        }
        sections.push_back(ParSection{i, offset, decomp_size});
        offset += stored_size;
    }
    return sections;
}

static int find_bytes(const std::vector<char>& data, const std::vector<unsigned char>& pattern, size_t start, size_t end) {
    if (pattern.empty() || start >= end || pattern.size() > end - start) return -1;
    for (size_t i = start; i + pattern.size() <= end; ++i) {
        bool ok = true;
        for (size_t j = 0; j < pattern.size(); ++j) {
            if (static_cast<unsigned char>(data[i + j]) != pattern[j]) {
                ok = false;
                break;
            }
        }
        if (ok) return static_cast<int>(i);
    }
    return -1;
}

static std::pair<std::string, std::string> find_descriptor_names(
    const std::vector<char>& data,
    size_t region_start,
    size_t desc_start
) {
    std::vector<std::string> names;
    size_t cursor = desc_start;
    for (int n = 0; n < 2; ++n) {
        bool found = false;
        for (size_t back = 1; back < 200 && cursor >= region_start + back; ++back) {
            const size_t pos = cursor - back;
            const unsigned char candidate_len = static_cast<unsigned char>(data[pos]);
            if (candidate_len == 0 || candidate_len != back - 1) continue;
            bool ascii = true;
            for (size_t p = pos + 1; p < cursor; ++p) {
                const unsigned char ch = static_cast<unsigned char>(data[p]);
                if (ch < 32 || ch >= 127) {
                    ascii = false;
                    break;
                }
            }
            if (!ascii || cursor <= pos + 1) continue;
            names.emplace_back(data.data() + pos + 1, data.data() + cursor);
            cursor = pos;
            found = true;
            break;
        }
        if (!found) {
            std::ostringstream unknown;
            unknown << "unknown_" << std::hex << (desc_start - region_start);
            names.push_back(unknown.str());
        }
    }
    std::reverse(names.begin(), names.end());
    return {names.size() > 0 ? names[0] : "", names.size() > 1 ? names[1] : ""};
}

static std::vector<PacDescriptor> find_pac_descriptors(
    const std::vector<char>& data,
    const ParSection& sec0,
    int n_lods
) {
    std::vector<PacDescriptor> descriptors;
    std::set<size_t> seen_starts;
    const size_t region_start = sec0.offset;
    const size_t region_end = static_cast<size_t>(sec0.offset) + sec0.size;
    if (region_end > data.size() || region_start >= region_end) return descriptors;
    const int pad_len = std::max(4, n_lods);

    auto append_descriptor = [&](size_t pattern_pos, int stored_lod_count, int vc_off, int ic_off) {
        if (pattern_pos < 35) return;
        const size_t desc_start = pattern_pos - 35;
        if (desc_start < region_start || !seen_starts.insert(desc_start).second) return;
        if (desc_start + static_cast<size_t>(ic_off) + static_cast<size_t>(stored_lod_count) * 4u > region_end) return;
        if (static_cast<unsigned char>(data[desc_start]) != 0x01) return;
        PacDescriptor desc;
        try {
            desc.bbox_min = Vec3{
                read_f32(data, desc_start + 3 + 2 * 4),
                read_f32(data, desc_start + 3 + 3 * 4),
                read_f32(data, desc_start + 3 + 4 * 4),
            };
            desc.bbox_extent = Vec3{
                read_f32(data, desc_start + 3 + 5 * 4),
                read_f32(data, desc_start + 3 + 6 * 4),
                read_f32(data, desc_start + 3 + 7 * 4),
            };
            for (int i = 0; i < stored_lod_count && i < pad_len && i < 10; ++i) {
                desc.vertex_counts[static_cast<size_t>(i)] = read_u16(data, desc_start + vc_off + static_cast<size_t>(i) * 2u);
                desc.index_counts[static_cast<size_t>(i)] = read_u32(data, desc_start + ic_off + static_cast<size_t>(i) * 4u);
            }
        } catch (...) {
            return;
        }
        bool any_vertices = false;
        for (std::uint32_t count : desc.vertex_counts) {
            if (count > 0) any_vertices = true;
            if (count > 200000) return;
        }
        for (std::uint32_t count : desc.index_counts) {
            if (count > 20000000) return;
        }
        if (!any_vertices) return;
        auto names = find_descriptor_names(data, region_start, desc_start);
        desc.name = names.first;
        desc.material = names.second;
        desc.stored_lod_count = stored_lod_count;
        desc.descriptor_offset = static_cast<std::uint32_t>(desc_start);
        descriptors.push_back(desc);
    };

    struct PatternSpec {
        std::vector<unsigned char> pattern;
        int lod_count;
        int vc_off;
        int ic_off;
        int reject_prev;
    };
    const std::vector<PatternSpec> specs = {
        {{0x04, 0x00, 0x01, 0x02, 0x03}, 4, 40, 48, -1},
        {{0x03, 0x00, 0x01, 0x01, 0x02}, 3, 40, 46, -1},
        {{0x03, 0x00, 0x01, 0x02}, 3, 40, 46, 0x04},
        {{0x02, 0x00, 0x01}, 2, 40, 44, 0x03},
    };
    for (const PatternSpec& spec : specs) {
        size_t pos = region_start;
        while (true) {
            const int found = find_bytes(data, spec.pattern, pos, region_end);
            if (found < 0) break;
            const size_t idx = static_cast<size_t>(found);
            bool accept = true;
            if (spec.reject_prev >= 0 && idx > region_start) {
                const unsigned char prev = static_cast<unsigned char>(data[idx - 1]);
                if (spec.lod_count == 3) accept = prev != 0x04;
                if (spec.lod_count == 2) accept = prev != 0x03 && prev != 0x04;
            }
            if (accept) append_descriptor(idx, spec.lod_count, spec.vc_off, spec.ic_off);
            pos = idx + spec.pattern.size();
        }
    }
    std::sort(descriptors.begin(), descriptors.end(), [](const PacDescriptor& a, const PacDescriptor& b) {
        return a.descriptor_offset < b.descriptor_offset;
    });
    return descriptors;
}

static float decode_pac_position(std::uint16_t value, float min_value, float extent) {
    if (std::abs(extent) < 1.0e-8f) return min_value;
    return min_value + (static_cast<float>(value) / 32767.0f) * extent;
}

static Vec3 decode_pac_normal(const std::vector<char>& data, size_t rec_off) {
    if (rec_off + 20 > data.size()) return Vec3{0.0f, 1.0f, 0.0f};
    const std::uint32_t packed = read_u32(data, rec_off + 16);
    const std::uint32_t nx_raw = (packed >> 0) & 0x3FFu;
    const std::uint32_t ny_raw = (packed >> 10) & 0x3FFu;
    const std::uint32_t nz_raw = (packed >> 20) & 0x3FFu;
    return vec_normalize(Vec3{
        static_cast<float>(ny_raw) / 511.5f - 1.0f,
        static_cast<float>(nz_raw) / 511.5f - 1.0f,
        static_cast<float>(nx_raw) / 511.5f - 1.0f,
    });
}

static int find_pac_section_index_start(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    const std::vector<PacDescriptor>& descriptors,
    int lod,
    int after_verts
) {
    const PacDescriptor* first = nullptr;
    for (const PacDescriptor& desc : descriptors) {
        if (lod >= 0 && lod < 10 && desc.vertex_counts[static_cast<size_t>(lod)] > 0) {
            first = &desc;
            break;
        }
    }
    if (first == nullptr) return -1;
    const std::uint32_t first_vc = first->vertex_counts[static_cast<size_t>(lod)];
    for (int adj = 0; after_verts + adj + 6 <= static_cast<int>(geom_sec.size); adj += 2) {
        const int trial = after_verts + adj;
        const size_t base = static_cast<size_t>(geom_sec.offset) + trial;
        const std::uint16_t v0 = read_u16(data, base);
        const std::uint16_t v1 = read_u16(data, base + 2);
        const std::uint16_t v2 = read_u16(data, base + 4);
        if (v0 == 0 && v1 < first_vc && v2 < first_vc) return trial;
    }
    return -1;
}

static std::pair<int, int> find_pac_section_layout(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    const std::vector<PacDescriptor>& descriptors,
    int lod,
    int total_indices
) {
    std::uint32_t total_verts = 0;
    for (const PacDescriptor& desc : descriptors) {
        total_verts += desc.vertex_counts[static_cast<size_t>(lod)];
    }
    const int primary_bytes = static_cast<int>(total_verts) * 40;
    const int index_bytes = total_indices * 2;
    if (primary_bytes + index_bytes >= static_cast<int>(geom_sec.size)) {
        return {0, primary_bytes};
    }
    const int gap = static_cast<int>(geom_sec.size) - primary_bytes - index_bytes;
    if (gap <= 0) return {0, primary_bytes};
    const int secondary_bytes = (gap / 40) * 40;
    int best_v_start = 0;
    int best_i_start = primary_bytes + secondary_bytes;
    for (int n_secondary = 0; n_secondary <= gap / 40; ++n_secondary) {
        const int v_start = n_secondary * 40;
        const int all_verts_end = v_start + primary_bytes;
        if (all_verts_end >= static_cast<int>(geom_sec.size)) break;
        const int idx_start = find_pac_section_index_start(data, geom_sec, descriptors, lod, all_verts_end);
        if (idx_start >= 0 && idx_start + index_bytes <= static_cast<int>(geom_sec.size)) {
            best_v_start = v_start;
            best_i_start = idx_start;
            break;
        }
    }
    return {best_v_start, best_i_start};
}

static std::vector<std::uint32_t> read_pac_indices(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    int index_start,
    std::uint32_t index_count
) {
    std::vector<std::uint32_t> indices;
    if (index_count == 0 || index_start < 0 || static_cast<std::uint32_t>(index_start) >= geom_sec.size) return indices;
    const std::uint32_t max_count = std::min<std::uint32_t>(index_count, (geom_sec.size - static_cast<std::uint32_t>(index_start)) / 2u);
    indices.reserve(max_count);
    const size_t base = static_cast<size_t>(geom_sec.offset) + static_cast<size_t>(index_start);
    for (std::uint32_t i = 0; i < max_count; ++i) {
        indices.push_back(read_u16(data, base + static_cast<size_t>(i) * 2u));
    }
    return indices;
}

static NativeSubmesh decode_pac_submesh_vertices(
    const std::vector<char>& data,
    const ParSection& geom_sec,
    const PacDescriptor& desc,
    int vertex_start,
    std::uint32_t vertex_count,
    const std::vector<std::uint32_t>& indices,
    int source_submesh_index
) {
    NativeSubmesh mesh;
    mesh.name = desc.name;
    mesh.material = desc.material.empty() ? desc.name : desc.material;
    mesh.source_submesh_index = source_submesh_index;
    mesh.positions.reserve(vertex_count);
    mesh.uvs.reserve(vertex_count);
    mesh.normals.reserve(vertex_count);
    for (std::uint32_t vi = 0; vi < vertex_count; ++vi) {
        const size_t rec_off = static_cast<size_t>(geom_sec.offset) + static_cast<size_t>(vertex_start) + static_cast<size_t>(vi) * 40u;
        if (rec_off + 40 > data.size()) break;
        const std::uint16_t xu = read_u16(data, rec_off);
        const std::uint16_t yu = read_u16(data, rec_off + 2);
        const std::uint16_t zu = read_u16(data, rec_off + 4);
        mesh.positions.push_back(Vec3{
            decode_pac_position(xu, desc.bbox_min.x, desc.bbox_extent.x),
            decode_pac_position(yu, desc.bbox_min.y, desc.bbox_extent.y),
            decode_pac_position(zu, desc.bbox_min.z, desc.bbox_extent.z),
        });
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(vi));
        const float u = half_to_float(read_u16(data, rec_off + 8));
        const float v = half_to_float(read_u16(data, rec_off + 10));
        mesh.uvs.push_back(Vec2{std::isfinite(u) ? u : 0.0f, std::isfinite(v) ? v : 0.0f});
        mesh.normals.push_back(decode_pac_normal(data, rec_off));
    }
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        const std::uint32_t a = indices[i];
        const std::uint32_t b = indices[i + 1];
        const std::uint32_t c = indices[i + 2];
        if (a < mesh.positions.size() && b < mesh.positions.size() && c < mesh.positions.size() && a != b && b != c && a != c) {
            mesh.indices.push_back(a);
            mesh.indices.push_back(b);
            mesh.indices.push_back(c);
        }
    }
    return mesh;
}

static std::vector<NativeSubmesh> parse_pac_geometry_section(
    const std::vector<char>& data,
    const std::vector<PacDescriptor>& descriptors,
    const ParSection& geom_sec,
    int lod
) {
    std::vector<NativeSubmesh> output;
    if (lod < 0 || lod >= 10) return output;
    int total_indices = 0;
    for (const PacDescriptor& desc : descriptors) {
        total_indices += static_cast<int>(desc.index_counts[static_cast<size_t>(lod)]);
    }
    const auto layout = find_pac_section_layout(data, geom_sec, descriptors, lod, total_indices);
    const int vert_base = layout.first;
    int idx_byte_offset = layout.second;
    const int index_region_start = idx_byte_offset;
    std::vector<int> desc_vert_offsets;
    desc_vert_offsets.reserve(descriptors.size());
    int cursor = vert_base;
    for (const PacDescriptor& desc : descriptors) {
        desc_vert_offsets.push_back(cursor);
        cursor += static_cast<int>(desc.vertex_counts[static_cast<size_t>(lod)]) * 40;
    }

    for (size_t di = 0; di < descriptors.size(); ++di) {
        const PacDescriptor& desc = descriptors[di];
        const std::uint32_t vc = desc.vertex_counts[static_cast<size_t>(lod)];
        const std::uint32_t ic = desc.index_counts[static_cast<size_t>(lod)];
        if (vc == 0 && ic == 0) continue;
        std::vector<std::uint32_t> indices = read_pac_indices(data, geom_sec, idx_byte_offset, ic);
        idx_byte_offset += static_cast<int>(ic) * 2;
        std::uint32_t owner_vc = vc;
        int owner_idx = static_cast<int>(di);
        const auto max_it = std::max_element(indices.begin(), indices.end());
        const std::uint32_t max_index = max_it == indices.end() ? 0u : *max_it;
        if (max_index >= vc) {
            for (size_t pj = 0; pj < descriptors.size(); ++pj) {
                if (pj != di && descriptors[pj].vertex_counts[static_cast<size_t>(lod)] > max_index) {
                    owner_idx = static_cast<int>(pj);
                    owner_vc = descriptors[pj].vertex_counts[static_cast<size_t>(lod)];
                    break;
                }
            }
            if (owner_idx == static_cast<int>(di)) {
                const int available_vc = std::max(0, (index_region_start - desc_vert_offsets[di]) / 40);
                if (max_index < static_cast<std::uint32_t>(available_vc)) owner_vc = max_index + 1u;
            }
        }
        NativeSubmesh mesh = decode_pac_submesh_vertices(
            data,
            geom_sec,
            descriptors[static_cast<size_t>(owner_idx)],
            desc_vert_offsets[static_cast<size_t>(owner_idx)],
            owner_vc,
            indices,
            static_cast<int>(di)
        );
        mesh.name = desc.name;
        mesh.material = desc.material.empty() ? desc.name : desc.material;
        if (!mesh.positions.empty() && mesh.indices.size() >= 3) output.push_back(std::move(mesh));
    }
    return output;
}

static std::vector<NativeSubmesh> parse_pac_submeshes(const std::vector<char>& data) {
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") {
        throw std::runtime_error("selected PAC is missing a PAR header");
    }
    const std::vector<ParSection> sections = parse_par_sections(data);
    if (sections.empty()) {
        throw std::runtime_error("native PAC parser does not yet support compressed PAR sections");
    }
    std::map<int, ParSection> by_index;
    for (const ParSection& section : sections) by_index[section.index] = section;
    auto sec0_it = by_index.find(0);
    if (sec0_it == by_index.end()) throw std::runtime_error("PAC section 0 is missing");
    const ParSection& sec0 = sec0_it->second;
    if (static_cast<size_t>(sec0.offset) + 5 > data.size()) throw std::runtime_error("PAC section 0 is truncated");
    const int n_lods = static_cast<unsigned char>(data[sec0.offset + 4]);
    if (n_lods <= 0 || n_lods > 10) throw std::runtime_error("PAC LOD count is unsupported");
    const std::vector<PacDescriptor> descriptors = find_pac_descriptors(data, sec0, n_lods);
    if (descriptors.empty()) throw std::runtime_error("native PAC parser found no submesh descriptors");

    struct Candidate {
        int faces = 0;
        int vertices = 0;
        int submeshes = 0;
        int geom_section_idx = 0;
        std::vector<NativeSubmesh> meshes;
    };
    std::vector<Candidate> candidates;
    for (int geom_section_idx : {4, 3, 2, 1}) {
        auto it = by_index.find(geom_section_idx);
        if (it == by_index.end()) continue;
        const int lod = 4 - geom_section_idx;
        if (lod < 0 || lod >= n_lods) continue;
        std::vector<NativeSubmesh> meshes = parse_pac_geometry_section(data, descriptors, it->second, lod);
        int faces = 0;
        int vertices = 0;
        for (const NativeSubmesh& mesh : meshes) {
            faces += static_cast<int>(mesh.indices.size() / 3u);
            vertices += static_cast<int>(mesh.positions.size());
        }
        if (!meshes.empty() && faces > 0) {
            candidates.push_back(Candidate{faces, vertices, static_cast<int>(meshes.size()), geom_section_idx, std::move(meshes)});
        }
    }
    if (candidates.empty()) throw std::runtime_error("native PAC parser found no renderable geometry sections");
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        if (a.faces != b.faces) return a.faces > b.faces;
        if (a.vertices != b.vertices) return a.vertices > b.vertices;
        if (a.submeshes != b.submeshes) return a.submeshes > b.submeshes;
        return a.geom_section_idx > b.geom_section_idx;
    });
    return std::move(candidates.front().meshes);
}

struct NativeMeshParseResult {
    std::vector<NativeSubmesh> meshes;
    std::string parser;
    int lod_count = 0;
};

static float dequantize_u16(std::uint16_t value, float minimum, float maximum) {
    return minimum + (static_cast<float>(value) / 65535.0f) * (maximum - minimum);
}

static float dequantize_i16(std::int16_t value, float minimum, float maximum) {
    return minimum + ((static_cast<float>(value) + 32768.0f) / 65536.0f) * (maximum - minimum);
}

static void compute_missing_normals(NativeSubmesh& mesh) {
    if (mesh.normals.size() == mesh.positions.size()) return;
    mesh.normals.assign(mesh.positions.size(), Vec3{});
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() || ic >= mesh.positions.size()) continue;
        const Vec3 ab = vec_sub(mesh.positions[ib], mesh.positions[ia]);
        const Vec3 ac = vec_sub(mesh.positions[ic], mesh.positions[ia]);
        const Vec3 normal = vec_cross(ab, ac);
        if (vec_dot(normal, normal) <= 1.0e-18f) continue;
        mesh.normals[ia] = vec_add(mesh.normals[ia], normal);
        mesh.normals[ib] = vec_add(mesh.normals[ib], normal);
        mesh.normals[ic] = vec_add(mesh.normals[ic], normal);
    }
    for (Vec3& normal : mesh.normals) {
        normal = vec_normalize(normal);
    }
}

static bool native_mesh_renderable(const NativeSubmesh& mesh) {
    if (mesh.positions.size() < 3 || mesh.indices.size() < 3) return false;
    Vec3 min_v{1.0e30f, 1.0e30f, 1.0e30f};
    Vec3 max_v{-1.0e30f, -1.0e30f, -1.0e30f};
    for (const Vec3& p : mesh.positions) {
        min_v.x = std::min(min_v.x, p.x); min_v.y = std::min(min_v.y, p.y); min_v.z = std::min(min_v.z, p.z);
        max_v.x = std::max(max_v.x, p.x); max_v.y = std::max(max_v.y, p.y); max_v.z = std::max(max_v.z, p.z);
    }
    const float dim = std::max({max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z});
    if (dim <= 1.0e-9f || !std::isfinite(dim)) return false;
    int non_degenerate = 0;
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() || ic >= mesh.positions.size()) continue;
        const Vec3 normal = vec_cross(vec_sub(mesh.positions[ib], mesh.positions[ia]), vec_sub(mesh.positions[ic], mesh.positions[ia]));
        if (vec_dot(normal, normal) > 1.0e-18f && ++non_degenerate >= 1) return true;
    }
    return false;
}

static void finalize_native_meshes(std::vector<NativeSubmesh>& meshes) {
    std::vector<NativeSubmesh> filtered;
    filtered.reserve(meshes.size());
    for (NativeSubmesh& mesh : meshes) {
        if (!native_mesh_renderable(mesh)) continue;
        compute_missing_normals(mesh);
        filtered.push_back(std::move(mesh));
    }
    meshes = std::move(filtered);
}

struct RawPamEntry {
    int index = 0;
    std::uint32_t vertex_count = 0;
    std::uint32_t index_count = 0;
    std::uint32_t vertex_element_offset = 0;
    std::uint32_t index_element_offset = 0;
    std::string texture_name;
    std::string material_name;
};

static constexpr int kPamSubmeshTableOffset = 1040;
static constexpr int kPamSubmeshStride = 536;
static constexpr int kPamHeaderMeshCountOffset = 16;
static constexpr int kPamHeaderBboxMinOffset = 20;
static constexpr int kPamHeaderBboxMaxOffset = 32;
static constexpr int kPamHeaderGeomOffset = 60;
static constexpr int kPamGlobalVertexBase = 3068;
static constexpr int kPamGlobalIndexOffset = 104512;
static constexpr int kPamTextureNameOffset = 16;
static constexpr int kPamMaterialNameOffset = 272;
static constexpr int kPamNameMaxLength = 256;
static constexpr int kPamlodHeaderLodCountOffset = 0;
static constexpr int kPamlodHeaderGeomOffset = 4;
static constexpr int kPamlodHeaderBboxMinOffset = 16;
static constexpr int kPamlodHeaderBboxMaxOffset = 28;
static constexpr int kPamlodEntryTableOffset = 80;

static const std::array<int, 16> kPamCandidateStrides = {
    6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 40
};
static const std::array<int, 16> kPamGlobalVertexBaseCandidates = {
    kPamGlobalVertexBase, 0, 256, 512, 1024, 1536, 2048, 2560,
    2816, 3328, 3584, 4096, 4608, 5120, 6144, 7168
};

static Vec3 read_vec3_f32(const std::vector<char>& data, size_t offset) {
    return Vec3{read_f32(data, offset), read_f32(data, offset + 4), read_f32(data, offset + 8)};
}

static std::vector<RawPamEntry> read_pam_entries(const std::vector<char>& data, int mesh_count) {
    std::vector<RawPamEntry> entries;
    for (int i = 0; i < mesh_count; ++i) {
        const size_t off = static_cast<size_t>(kPamSubmeshTableOffset) + static_cast<size_t>(i) * kPamSubmeshStride;
        if (off + kPamSubmeshStride > data.size()) break;
        entries.push_back(RawPamEntry{
            i,
            read_u32(data, off),
            read_u32(data, off + 4),
            read_u32(data, off + 8),
            read_u32(data, off + 12),
            read_c_string(data, off + kPamTextureNameOffset, kPamNameMaxLength),
            read_c_string(data, off + kPamMaterialNameOffset, kPamNameMaxLength),
        });
    }
    return entries;
}

static bool pam_uses_combined_layout(const std::vector<RawPamEntry>& entries) {
    if (entries.size() <= 1) return false;
    std::uint32_t expected_vertex_offset = 0;
    std::uint32_t expected_index_offset = 0;
    for (const RawPamEntry& entry : entries) {
        if (entry.vertex_element_offset != expected_vertex_offset || entry.index_element_offset != expected_index_offset) return false;
        expected_vertex_offset += entry.vertex_count;
        expected_index_offset += entry.index_count;
    }
    return true;
}

static bool indices_fit_vertex_count(
    const std::vector<char>& data,
    size_t index_offset,
    std::uint32_t index_count,
    std::uint32_t vertex_count
) {
    if (index_offset + static_cast<size_t>(index_count) * 2u > data.size()) return false;
    for (std::uint32_t i = 0; i < index_count; ++i) {
        if (read_u16(data, index_offset + static_cast<size_t>(i) * 2u) >= vertex_count) return false;
    }
    return true;
}

static NativeSubmesh parse_quantized_pam_mesh(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    size_t vertex_base,
    size_t index_offset,
    int stride,
    const Vec3& bbox_min,
    const Vec3& bbox_max
) {
    NativeSubmesh mesh;
    mesh.name = raw.texture_name.empty() ? raw.material_name : raw.texture_name;
    mesh.material = raw.material_name.empty() ? raw.texture_name : raw.material_name;
    mesh.source_submesh_index = raw.index;
    if (vertex_base >= data.size() || index_offset + static_cast<size_t>(raw.index_count) * 2u > data.size()) return mesh;
    std::vector<std::uint32_t> source_indices;
    source_indices.reserve(raw.index_count);
    std::set<std::uint32_t> unique_indices;
    for (std::uint32_t i = 0; i < raw.index_count; ++i) {
        std::uint32_t index = read_u16(data, index_offset + static_cast<size_t>(i) * 2u);
        source_indices.push_back(index);
        unique_indices.insert(index);
    }
    std::unordered_map<std::uint32_t, std::uint32_t> source_to_local;
    for (std::uint32_t source_index : unique_indices) {
        const size_t voff = vertex_base + static_cast<size_t>(source_index) * static_cast<size_t>(stride);
        if (voff + 6 > data.size()) continue;
        source_to_local[source_index] = static_cast<std::uint32_t>(mesh.positions.size());
        mesh.positions.push_back(Vec3{
            dequantize_u16(read_u16(data, voff), bbox_min.x, bbox_max.x),
            dequantize_u16(read_u16(data, voff + 2), bbox_min.y, bbox_max.y),
            dequantize_u16(read_u16(data, voff + 4), bbox_min.z, bbox_max.z),
        });
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(source_index));
        if (stride >= 12 && voff + 12 <= data.size()) {
            mesh.uvs.push_back(Vec2{
                half_to_float(read_u16(data, voff + 8)),
                half_to_float(read_u16(data, voff + 10)),
            });
        } else {
            mesh.uvs.push_back(Vec2{});
        }
    }
    for (size_t i = 0; i + 2 < source_indices.size(); i += 3) {
        auto a = source_to_local.find(source_indices[i]);
        auto b = source_to_local.find(source_indices[i + 1]);
        auto c = source_to_local.find(source_indices[i + 2]);
        if (a == source_to_local.end() || b == source_to_local.end() || c == source_to_local.end()) continue;
        if (a->second == b->second || b->second == c->second || a->second == c->second) continue;
        mesh.indices.push_back(a->second);
        mesh.indices.push_back(b->second);
        mesh.indices.push_back(c->second);
    }
    return mesh;
}

static NativeSubmesh parse_global_pam_mesh_at(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    int geom_offset,
    const Vec3& bbox_min,
    const Vec3& bbox_max,
    size_t index_offset,
    int global_vertex_base
) {
    NativeSubmesh mesh;
    mesh.name = raw.texture_name.empty() ? raw.material_name : raw.texture_name;
    mesh.material = raw.material_name.empty() ? raw.texture_name : raw.material_name;
    mesh.source_submesh_index = raw.index;
    if (index_offset + static_cast<size_t>(raw.index_count) * 2u > data.size()) return mesh;
    std::vector<std::uint32_t> source_indices;
    source_indices.reserve(raw.index_count);
    std::set<std::uint32_t> unique_indices;
    for (std::uint32_t i = 0; i < raw.index_count; ++i) {
        std::uint32_t index = read_u16(data, index_offset + static_cast<size_t>(i) * 2u);
        source_indices.push_back(index);
        unique_indices.insert(index);
    }
    std::unordered_map<std::uint32_t, std::uint32_t> source_to_local;
    for (std::uint32_t source_index : unique_indices) {
        const int vertex_index = static_cast<int>(source_index) - global_vertex_base;
        if (vertex_index < 0) continue;
        const size_t voff = static_cast<size_t>(geom_offset) + static_cast<size_t>(vertex_index) * 6u;
        if (voff + 6 > data.size()) continue;
        source_to_local[source_index] = static_cast<std::uint32_t>(mesh.positions.size());
        mesh.positions.push_back(Vec3{
            dequantize_i16(read_i16(data, voff), bbox_min.x, bbox_max.x),
            dequantize_i16(read_i16(data, voff + 2), bbox_min.y, bbox_max.y),
            dequantize_i16(read_i16(data, voff + 4), bbox_min.z, bbox_max.z),
        });
        mesh.uvs.push_back(Vec2{});
        mesh.source_vertex_indices.push_back(static_cast<std::int32_t>(source_index));
    }
    for (size_t i = 0; i + 2 < source_indices.size(); i += 3) {
        auto a = source_to_local.find(source_indices[i]);
        auto b = source_to_local.find(source_indices[i + 1]);
        auto c = source_to_local.find(source_indices[i + 2]);
        if (a == source_to_local.end() || b == source_to_local.end() || c == source_to_local.end()) continue;
        if (a->second == b->second || b->second == c->second || a->second == c->second) continue;
        mesh.indices.push_back(a->second);
        mesh.indices.push_back(b->second);
        mesh.indices.push_back(c->second);
    }
    return mesh;
}

static float mesh_parse_score(const NativeSubmesh& mesh, const RawPamEntry& raw) {
    if (!native_mesh_renderable(mesh)) return -1.0e30f;
    std::set<std::uint32_t> referenced;
    int non_degenerate = 0;
    float max_edge2 = 0.0f;
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t ia = mesh.indices[i];
        const std::uint32_t ib = mesh.indices[i + 1];
        const std::uint32_t ic = mesh.indices[i + 2];
        if (ia >= mesh.positions.size() || ib >= mesh.positions.size() || ic >= mesh.positions.size()) continue;
        referenced.insert(ia); referenced.insert(ib); referenced.insert(ic);
        const Vec3 ab = vec_sub(mesh.positions[ib], mesh.positions[ia]);
        const Vec3 ac = vec_sub(mesh.positions[ic], mesh.positions[ia]);
        if (vec_dot(vec_cross(ab, ac), vec_cross(ab, ac)) > 1.0e-18f) ++non_degenerate;
        max_edge2 = std::max({max_edge2, vec_dot(ab, ab), vec_dot(ac, ac), vec_dot(vec_sub(mesh.positions[ic], mesh.positions[ib]), vec_sub(mesh.positions[ic], mesh.positions[ib]))});
    }
    const float face_ratio = static_cast<float>(mesh.indices.size() / 3u) / static_cast<float>(std::max<std::uint32_t>(1, raw.index_count / 3u));
    const float ref_ratio = static_cast<float>(referenced.size()) / static_cast<float>(std::max<size_t>(1, mesh.positions.size()));
    const float nondeg_ratio = static_cast<float>(non_degenerate) / static_cast<float>(std::max<size_t>(1, mesh.indices.size() / 3u));
    return face_ratio * 4.0f + ref_ratio * 3.0f + nondeg_ratio * 2.0f - std::sqrt(std::max(0.0f, max_edge2)) * 0.35f;
}

static std::vector<int> pam_global_index_offset_candidates(
    const std::vector<char>& data,
    int geom_offset,
    const RawPamEntry& raw
) {
    std::vector<int> candidates;
    if (raw.index_count < 120 || raw.vertex_count < 256) return candidates;
    const int sample_count = static_cast<int>(std::min<std::uint32_t>(raw.index_count, 180));
    const int min_unique = std::min<int>(static_cast<int>(raw.vertex_count), std::max(12, std::min(24, sample_count / 6)));
    int search_start = std::max(kPamGlobalIndexOffset, geom_offset);
    int search_stop = static_cast<int>(data.size()) - sample_count * 2;
    if (search_stop <= search_start) return candidates;
    if (search_stop - search_start > 8 * 1024 * 1024) search_stop = search_start + 8 * 1024 * 1024;
    const int max_index_value = static_cast<int>(raw.vertex_count) + 8192;
    const auto started = std::chrono::steady_clock::now();
    for (int off = search_start; off <= search_stop; off += 2) {
        if ((off & 0x1FF) == 0) {
            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
            if (elapsed > 0.35) break;
        }
        std::set<std::uint16_t> sampled;
        bool valid = true;
        for (int i = 0; i < sample_count; i += 3) {
            const std::uint16_t value = read_u16(data, static_cast<size_t>(off) + static_cast<size_t>(i) * 2u);
            if (value > max_index_value) {
                valid = false;
                break;
            }
            sampled.insert(value);
        }
        if (!valid || static_cast<int>(sampled.size()) < min_unique) continue;
        candidates.push_back(off);
        if (candidates.size() >= 12) break;
    }
    return candidates;
}

static NativeSubmesh parse_best_global_pam_mesh(
    const std::vector<char>& data,
    const RawPamEntry& raw,
    int geom_offset,
    const Vec3& bbox_min,
    const Vec3& bbox_max
) {
    NativeSubmesh best = parse_global_pam_mesh_at(
        data,
        raw,
        geom_offset,
        bbox_min,
        bbox_max,
        static_cast<size_t>(kPamGlobalIndexOffset) + static_cast<size_t>(raw.index_element_offset) * 2u,
        kPamGlobalVertexBase
    );
    float best_score = mesh_parse_score(best, raw);
    for (int candidate_index_offset : pam_global_index_offset_candidates(data, geom_offset, raw)) {
        for (int global_vertex_base : kPamGlobalVertexBaseCandidates) {
            NativeSubmesh candidate = parse_global_pam_mesh_at(
                data,
                raw,
                geom_offset,
                bbox_min,
                bbox_max,
                static_cast<size_t>(candidate_index_offset),
                global_vertex_base
            );
            const float score = mesh_parse_score(candidate, raw);
            if (score > best_score) {
                best_score = score;
                best = std::move(candidate);
            }
        }
    }
    return best;
}

static std::optional<std::pair<int, size_t>> find_combined_pam_layout(
    const std::vector<char>& data,
    const std::vector<RawPamEntry>& entries,
    int geom_offset
) {
    std::uint64_t total_vertices = 0;
    std::uint64_t total_indices = 0;
    for (const RawPamEntry& entry : entries) {
        total_vertices += entry.vertex_count;
        total_indices += entry.index_count;
    }
    if (total_vertices == 0 || total_indices == 0 || geom_offset < 0 || static_cast<size_t>(geom_offset) >= data.size()) return std::nullopt;
    const double target_stride = static_cast<double>(data.size() - static_cast<size_t>(geom_offset) - total_indices * 2u) / static_cast<double>(total_vertices);
    std::vector<int> strides(kPamCandidateStrides.begin(), kPamCandidateStrides.end());
    std::sort(strides.begin(), strides.end(), [target_stride](int a, int b) {
        return std::abs(static_cast<double>(a) - target_stride) < std::abs(static_cast<double>(b) - target_stride);
    });
    for (int stride : strides) {
        const size_t index_block = static_cast<size_t>(geom_offset) + static_cast<size_t>(total_vertices) * static_cast<size_t>(stride);
        if (index_block + static_cast<size_t>(total_indices) * 2u > data.size()) continue;
        bool ok = true;
        for (const RawPamEntry& entry : entries) {
            if (!indices_fit_vertex_count(data, index_block + static_cast<size_t>(entry.index_element_offset) * 2u, entry.index_count, entry.vertex_count)) {
                ok = false;
                break;
            }
        }
        if (ok) return std::make_pair(stride, index_block);
    }
    return std::nullopt;
}

static std::optional<std::pair<int, size_t>> find_local_pam_layout(
    const std::vector<char>& data,
    int geom_offset,
    const RawPamEntry& raw
) {
    const size_t vertex_base = static_cast<size_t>(geom_offset) + raw.vertex_element_offset;
    if (vertex_base >= data.size()) return std::nullopt;
    for (int stride : kPamCandidateStrides) {
        const size_t index_offset = vertex_base + static_cast<size_t>(raw.vertex_count) * static_cast<size_t>(stride);
        if (indices_fit_vertex_count(data, index_offset, raw.index_count, raw.vertex_count)) {
            return std::make_pair(stride, index_offset);
        }
    }
    return std::nullopt;
}

static NativeMeshParseResult parse_pam_submeshes(const std::vector<char>& data) {
    if (data.size() < 64 || std::string(data.data(), data.data() + 4) != "PAR ") {
        throw std::runtime_error("selected PAM is missing a PAR header");
    }
    const Vec3 bbox_min = read_vec3_f32(data, kPamHeaderBboxMinOffset);
    const Vec3 bbox_max = read_vec3_f32(data, kPamHeaderBboxMaxOffset);
    const int geom_offset = static_cast<int>(read_u32(data, kPamHeaderGeomOffset));
    const int mesh_count = static_cast<int>(read_u32(data, kPamHeaderMeshCountOffset));
    if (geom_offset <= 0 || static_cast<size_t>(geom_offset) >= data.size() || mesh_count <= 0 || mesh_count > 4096) {
        throw std::runtime_error("PAM geometry header is invalid");
    }
    std::vector<RawPamEntry> entries = read_pam_entries(data, mesh_count);
    if (entries.empty()) throw std::runtime_error("PAM submesh table is empty");

    if (pam_uses_combined_layout(entries)) {
        auto layout = find_combined_pam_layout(data, entries, geom_offset);
        if (layout.has_value()) {
            std::vector<NativeSubmesh> meshes;
            for (const RawPamEntry& raw : entries) {
                if (raw.vertex_count == 0 || raw.index_count < 3) continue;
                meshes.push_back(parse_quantized_pam_mesh(
                    data,
                    raw,
                    static_cast<size_t>(geom_offset) + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(layout->first),
                    layout->second + static_cast<size_t>(raw.index_element_offset) * 2u,
                    layout->first,
                    bbox_min,
                    bbox_max
                ));
            }
            finalize_native_meshes(meshes);
            if (!meshes.empty()) return NativeMeshParseResult{std::move(meshes), "native_pam_combined", 0};
        }
    }

    std::vector<NativeSubmesh> local_meshes;
    const std::uint32_t max_global_index_count = data.size() > kPamGlobalIndexOffset
        ? static_cast<std::uint32_t>((data.size() - kPamGlobalIndexOffset) / 2u)
        : 0u;
    bool used_global = false;
    for (const RawPamEntry& raw : entries) {
        if (raw.vertex_count == 0 || raw.index_count < 3) continue;
        auto local_layout = find_local_pam_layout(data, geom_offset, raw);
        if (local_layout.has_value()) {
            local_meshes.push_back(parse_quantized_pam_mesh(
                data,
                raw,
                static_cast<size_t>(geom_offset) + raw.vertex_element_offset,
                local_layout->second,
                local_layout->first,
                bbox_min,
                bbox_max
            ));
        } else if (raw.index_element_offset + raw.index_count <= max_global_index_count) {
            used_global = true;
            local_meshes.push_back(parse_best_global_pam_mesh(data, raw, geom_offset, bbox_min, bbox_max));
        }
    }
    finalize_native_meshes(local_meshes);
    if (local_meshes.empty()) throw std::runtime_error("native PAM parser found no renderable geometry");
    return NativeMeshParseResult{std::move(local_meshes), used_global ? "native_pam_global" : "native_pam_local", 0};
}

static std::vector<RawPamEntry> read_pamlod_entries(const std::vector<char>& data, int geom_offset) {
    std::vector<RawPamEntry> entries;
    const int search_limit = std::max(kPamlodEntryTableOffset, geom_offset - 5);
    for (int off = kPamlodEntryTableOffset; off < search_limit; ++off) {
        if (!looks_like_dds_string(data, static_cast<size_t>(off), kPamNameMaxLength)) continue;
        const int entry_offset = off - 16;
        if (entry_offset < kPamlodEntryTableOffset || static_cast<size_t>(off) + kPamNameMaxLength > data.size()) continue;
        const std::uint32_t vc = read_u32(data, entry_offset);
        const std::uint32_t ic = read_u32(data, entry_offset + 4);
        if (vc == 0 || vc > 131072 || ic == 0 || (ic % 3) != 0) continue;
        entries.push_back(RawPamEntry{
            static_cast<int>(entries.size()),
            vc,
            ic,
            read_u32(data, off - 8),
            read_u32(data, off - 4),
            read_c_string(data, off, kPamNameMaxLength),
            read_c_string(data, static_cast<size_t>(off) + kPamNameMaxLength, kPamNameMaxLength),
        });
    }
    return entries;
}

static std::vector<std::vector<RawPamEntry>> group_pamlod_entries(const std::vector<RawPamEntry>& entries, int lod_count) {
    std::vector<std::vector<RawPamEntry>> groups;
    std::vector<RawPamEntry> current;
    std::uint32_t expected_vertex_offset = 0;
    std::uint32_t expected_index_offset = 0;
    for (const RawPamEntry& entry : entries) {
        if (!current.empty() && (entry.vertex_element_offset != expected_vertex_offset || entry.index_element_offset != expected_index_offset)) {
            groups.push_back(current);
            current.clear();
        }
        current.push_back(entry);
        expected_vertex_offset = entry.vertex_element_offset + entry.vertex_count;
        expected_index_offset = entry.index_element_offset + entry.index_count;
    }
    if (!current.empty()) groups.push_back(current);
    if (lod_count >= 0 && static_cast<int>(groups.size()) > lod_count) groups.resize(static_cast<size_t>(lod_count));
    return groups;
}

static std::vector<int> pamlod_padding_candidates() {
    std::vector<int> out;
    for (int i = 0; i < 64; i += 2) out.push_back(i);
    for (int i = 64; i < 512; i += 4) out.push_back(i);
    for (int i = 512; i < 4096; i += 8) out.push_back(i);
    return out;
}

static std::optional<std::tuple<size_t, int, size_t>> find_pamlod_group_layout(
    const std::vector<char>& data,
    size_t cursor,
    const std::vector<RawPamEntry>& group
) {
    std::uint64_t total_vertices = 0;
    std::uint64_t total_indices = 0;
    for (const RawPamEntry& raw : group) {
        total_vertices += raw.vertex_count;
        total_indices += raw.index_count;
    }
    if (total_vertices == 0 || total_indices == 0) return std::nullopt;
    std::vector<int> strides(kPamCandidateStrides.begin(), kPamCandidateStrides.end());
    std::sort(strides.begin(), strides.end(), [](int a, int b) {
        return std::pair<int, int>(std::abs(a - 20), a) < std::pair<int, int>(std::abs(b - 20), b);
    });
    for (int padding : pamlod_padding_candidates()) {
        const size_t vertex_base = cursor + static_cast<size_t>(padding);
        for (int stride : strides) {
            const size_t index_offset = vertex_base + static_cast<size_t>(total_vertices) * static_cast<size_t>(stride);
            if (index_offset + static_cast<size_t>(total_indices) * 2u > data.size()) continue;
            bool ok = true;
            for (const RawPamEntry& raw : group) {
                if (!indices_fit_vertex_count(data, index_offset + static_cast<size_t>(raw.index_element_offset) * 2u, raw.index_count, raw.vertex_count)) {
                    ok = false;
                    break;
                }
            }
            if (ok) return std::make_tuple(vertex_base, stride, index_offset);
        }
    }
    return std::nullopt;
}

static NativeMeshParseResult parse_pamlod_submeshes(const std::vector<char>& data) {
    if (data.size() < kPamlodEntryTableOffset) {
        throw std::runtime_error("selected PAMLOD is too small");
    }
    const int lod_count = static_cast<int>(read_u32(data, kPamlodHeaderLodCountOffset));
    const int geom_offset = static_cast<int>(read_u32(data, kPamlodHeaderGeomOffset));
    if (lod_count <= 0 || lod_count > 32 || geom_offset <= 0 || static_cast<size_t>(geom_offset) >= data.size()) {
        throw std::runtime_error("PAMLOD geometry header is invalid");
    }
    const Vec3 bbox_min = read_vec3_f32(data, kPamlodHeaderBboxMinOffset);
    const Vec3 bbox_max = read_vec3_f32(data, kPamlodHeaderBboxMaxOffset);
    std::vector<RawPamEntry> entries = read_pamlod_entries(data, geom_offset);
    if (entries.empty()) throw std::runtime_error("PAMLOD mesh table is empty");
    std::vector<std::vector<RawPamEntry>> groups = group_pamlod_entries(entries, lod_count);
    size_t cursor = static_cast<size_t>(geom_offset);
    for (const std::vector<RawPamEntry>& group : groups) {
        auto layout = find_pamlod_group_layout(data, cursor, group);
        if (!layout.has_value()) continue;
        const size_t vertex_base = std::get<0>(*layout);
        const int stride = std::get<1>(*layout);
        const size_t index_offset = std::get<2>(*layout);
        std::vector<NativeSubmesh> meshes;
        for (const RawPamEntry& raw : group) {
            meshes.push_back(parse_quantized_pam_mesh(
                data,
                raw,
                vertex_base + static_cast<size_t>(raw.vertex_element_offset) * static_cast<size_t>(stride),
                index_offset + static_cast<size_t>(raw.index_element_offset) * 2u,
                stride,
                bbox_min,
                bbox_max
            ));
        }
        finalize_native_meshes(meshes);
        if (!meshes.empty()) return NativeMeshParseResult{std::move(meshes), "native_pamlod_lod0", static_cast<int>(groups.size())};
        std::uint64_t total_indices = 0;
        for (const RawPamEntry& raw : group) total_indices += raw.index_count;
        cursor = index_offset + static_cast<size_t>(total_indices) * 2u;
    }
    throw std::runtime_error("native PAMLOD parser found no renderable LOD geometry");
}

static std::string texture_role_from_name(const std::string& raw_name) {
    const std::string name = lower_copy(raw_name);
    if (name.find("_n.dds") != std::string::npos || name.find("normal") != std::string::npos) return "normal";
    if (name.find("_disp.dds") != std::string::npos || name.find("height") != std::string::npos || name.find("displacement") != std::string::npos) return "height";
    if (name.find("_sp.dds") != std::string::npos || name.find("specular") != std::string::npos) return "specular";
    if (name.find("_ma.dds") != std::string::npos || name.find("_m.dds") != std::string::npos || name.find("material") != std::string::npos) return "material";
    if (name.find("_mg.dds") != std::string::npos || name.find("detail") != std::string::npos || name.find("grime") != std::string::npos || name.find("mask") != std::string::npos) return "detail";
    if (name.find("_o.dds") != std::string::npos || name.find("base") != std::string::npos || name.find("diffuse") != std::string::npos || name.find("albedo") != std::string::npos || name.find("texturelayer") != std::string::npos) return "base";
    return "base";
}

static bool role_is_technical_for_base(const std::string& role) {
    return role == "normal" || role == "height" || role == "material" || role == "detail" || role == "specular";
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

static bool technical_for_visible_base(const std::string& parameter_name, const std::string& raw_path, const std::string& role) {
    const std::string hint = lower_copy(parameter_name);
    const std::string compact_hint = std::regex_replace(hint, std::regex("[^a-z0-9]+"), "");
    if (role_is_technical_for_base(role)) return true;
    if (compact_hint.find("normal") != std::string::npos || compact_hint.find("height") != std::string::npos) return true;
    if (compact_hint.find("displacement") != std::string::npos || compact_hint.find("material") != std::string::npos) return true;
    if (compact_hint.find("roughness") != std::string::npos || compact_hint.find("metallic") != std::string::npos) return true;
    if (compact_hint.find("occlusion") != std::string::npos || compact_hint.find("opacity") != std::string::npos) return true;
    if (compact_hint.find("specular") != std::string::npos || compact_hint.find("orm") != std::string::npos) return true;
    if (compact_hint == "colorblendingmasktexture" || compact_hint == "detailmasktexture") return true;
    if (compact_hint.find("mask") != std::string::npos && compact_hint.find("diffuse") == std::string::npos && compact_hint.find("albedo") == std::string::npos && compact_hint.find("color") == std::string::npos) return true;
    if (path_has_suffix_stem(raw_path, "_n") || path_has_suffix_stem(raw_path, "_disp") || path_has_suffix_stem(raw_path, "_ma")) return true;
    if (path_has_suffix_stem(raw_path, "_mg") || path_has_suffix_stem(raw_path, "_sp") || path_has_suffix_stem(raw_path, "_m")) return true;
    if (path_has_suffix_stem(raw_path, "_orm") || path_has_suffix_stem(raw_path, "_rma") || path_has_suffix_stem(raw_path, "_mra")) return true;
    return false;
}

static std::string visible_class_for_binding(const std::string& parameter_name, const std::string& raw_path, const std::string& role) {
    if (technical_for_visible_base(parameter_name, raw_path, role)) return "technical";
    const std::string hint = std::regex_replace(lower_copy(parameter_name), std::regex("[^a-z0-9]+"), "");
    if (hint.find("grime") != std::string::npos || hint.find("detail") != std::string::npos || hint.find("layer") != std::string::npos || hint.find("blend") != std::string::npos || hint.find("decal") != std::string::npos) {
        return "layer_visible";
    }
    if (hint.find("basecolor") != std::string::npos || hint.find("basecolour") != std::string::npos || hint.find("albedo") != std::string::npos || hint.find("diffuse") != std::string::npos || hint.find("colortexture") != std::string::npos || hint.find("overlaycolor") != std::string::npos || hint.find("base") != std::string::npos) {
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
    if (normalized == "mesh_base_first") return visible_class == "primary_visible";
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
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "detail") return "detail_mask";
    if (role == "material") return "material_mask";
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
    const std::regex material_name_pattern("(?:_materialName|MaterialName|TechniqueName)=\"([^\"]+)\"", std::regex_constants::icase);
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

struct TechniqueParameterInfo {
    std::string name;
    std::string type;
    std::string srgb;
    std::string default_value;
    bool declared = false;
};

struct TechniqueIndex {
    std::unordered_map<std::string, TechniqueParameterInfo> parameters_by_name;
    std::set<std::string> technique_names;
    int files_scanned = 0;
    int parameters = 0;
    int texture_parameters = 0;
};

static void add_technique_parameter(TechniqueIndex& index, const std::string& tag) {
    const auto attrs = xml_attribute_map(tag);
    TechniqueParameterInfo info;
    info.name = xml_attr_value_from_map(attrs, {"Name", "_name"});
    if (info.name.empty()) return;
    info.type = xml_attr_value_from_map(attrs, {"Type", "_type"});
    info.srgb = xml_attr_value_from_map(attrs, {"sRGB", "SRGB", "Srgb"});
    info.default_value = xml_attr_value_from_map(attrs, {"DefaultValue", "Value", "_defaultValue"});
    info.declared = true;
    ++index.parameters;
    const std::string key = lower_copy(info.name);
    const std::string type_lower = lower_copy(info.type);
    if (type_lower.find("texture") != std::string::npos || key.find("texture") != std::string::npos) {
        ++index.texture_parameters;
    }
    auto found = index.parameters_by_name.find(key);
    if (found == index.parameters_by_name.end()) {
        index.parameters_by_name.emplace(key, info);
    } else {
        if (found->second.srgb.empty()) found->second.srgb = info.srgb;
        if (found->second.type.empty()) found->second.type = info.type;
        if (found->second.default_value.empty()) found->second.default_value = info.default_value;
    }
}

static TechniqueIndex build_technique_index_for_pamt(const PamtIndex& pamt_index) {
    TechniqueIndex index;
    for (const ArchiveEntryRef& ref : pamt_index.material_sidecars) {
        if (ref.extension != ".technique" && ref.extension != ".material") continue;
        std::vector<char> bytes;
        try {
            bytes = read_archive_ref_decoded_bytes(ref);
        } catch (...) {
            continue;
        }
        ++index.files_scanned;
        const std::string text(bytes.begin(), bytes.end());
        for (const std::string& tag : collect_xml_tag_blocks(text, "Technique")) {
            const std::string name = xml_attr_value_from_map(xml_attribute_map(tag), {"Name"});
            if (!name.empty()) index.technique_names.insert(name);
        }
        for (const std::string& tag : collect_xml_tag_blocks(text, "Parameter")) {
            add_technique_parameter(index, tag);
        }
    }
    return index;
}

static void merge_technique_index(TechniqueIndex& destination, const TechniqueIndex& source) {
    destination.files_scanned += source.files_scanned;
    destination.parameters += source.parameters;
    destination.texture_parameters += source.texture_parameters;
    destination.technique_names.insert(source.technique_names.begin(), source.technique_names.end());
    for (const auto& [key, value] : source.parameters_by_name) {
        auto found = destination.parameters_by_name.find(key);
        if (found == destination.parameters_by_name.end()) {
            destination.parameters_by_name.emplace(key, value);
        } else {
            if (found->second.srgb.empty()) found->second.srgb = value.srgb;
            if (found->second.type.empty()) found->second.type = value.type;
            if (found->second.default_value.empty()) found->second.default_value = value.default_value;
        }
    }
}

static const TechniqueIndex& cached_technique_index(const PamtIndex& pamt_index) {
    static std::map<std::string, TechniqueIndex> cache;
    const std::string key = fs::absolute(pamt_index.pamt_path).string();
    auto it = cache.find(key);
    if (it == cache.end()) {
        it = cache.emplace(key, build_technique_index_for_pamt(pamt_index)).first;
    }
    return it->second;
}

static std::vector<fs::path> package_root_pamt_paths(const fs::path& package_root) {
    std::vector<fs::path> paths;
    if (package_root.empty()) return paths;
    std::error_code ec;
    if (fs::is_regular_file(package_root, ec) && package_root.extension() == ".pamt") {
        paths.push_back(package_root);
        return paths;
    }
    if (!fs::is_directory(package_root, ec)) return paths;
    for (const fs::directory_entry& root_entry : fs::directory_iterator(package_root, ec)) {
        if (ec) break;
        if (root_entry.is_regular_file(ec) && root_entry.path().extension() == ".pamt") {
            paths.push_back(root_entry.path());
        } else if (root_entry.is_directory(ec)) {
            std::error_code inner_ec;
            for (const fs::directory_entry& child : fs::directory_iterator(root_entry.path(), inner_ec)) {
                if (inner_ec) break;
                if (child.is_regular_file(inner_ec) && child.path().extension() == ".pamt") {
                    paths.push_back(child.path());
                }
            }
        }
        if (paths.size() >= 64) break;
    }
    std::sort(paths.begin(), paths.end());
    paths.erase(std::unique(paths.begin(), paths.end()), paths.end());
    return paths;
}

static const TechniqueIndex& cached_package_technique_index(
    const EntryJob& job,
    const PamtIndex& primary_index
) {
    if (job.package_root.empty()) {
        return cached_technique_index(primary_index);
    }
    static std::map<std::string, TechniqueIndex> cache;
    const std::string key = fs::absolute(job.package_root).string();
    auto found = cache.find(key);
    if (found != cache.end()) return found->second;
    TechniqueIndex combined;
    std::set<std::string> seen_pamts;
    merge_technique_index(combined, cached_technique_index(primary_index));
    seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
    for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
        const std::string pamt_key = fs::absolute(pamt_path).string();
        if (!seen_pamts.insert(pamt_key).second) continue;
        try {
            merge_technique_index(combined, cached_technique_index(cached_pamt_index(pamt_path)));
        } catch (...) {
        }
    }
    return cache.emplace(key, std::move(combined)).first->second;
}

struct NativeMaterialGraph {
    int version = kNativeMaterialGraphVersion;
    std::string key;
    fs::path cache_path;
    bool persistent_cache_hit = false;
    int pamt_count = 0;
    size_t entry_count = 0;
    size_t material_sidecar_count = 0;
    size_t texture_candidate_count = 0;
    TechniqueIndex technique_index;
};

static size_t count_dds_basenames(const PamtIndex& index) {
    size_t count = 0;
    for (const auto& [basename, _refs] : index.by_basename) {
        if (lower_copy(basename).ends_with(".dds")) ++count;
    }
    return count;
}

static const NativeMaterialGraph& cached_native_material_graph(
    const EntryJob& job,
    const PamtIndex& primary_index
) {
    static std::map<std::string, NativeMaterialGraph> cache;
    const std::string root_key = job.package_root.empty()
        ? fs::absolute(primary_index.pamt_path).string()
        : fs::absolute(job.package_root).string();
    const std::string key = root_key + "|material_graph_v" + std::to_string(kNativeMaterialGraphVersion);
    auto found = cache.find(key);
    if (found != cache.end()) return found->second;

    NativeMaterialGraph graph;
    graph.key = hex64(fnv1a64(key));
    graph.cache_path = job.cache_root / "native_material_graph" / (graph.key + ".json");
    graph.persistent_cache_hit = fs::is_regular_file(graph.cache_path);
    graph.technique_index = cached_package_technique_index(job, primary_index);
    graph.pamt_count = 1;
    graph.entry_count = primary_index.entry_count;
    graph.material_sidecar_count = primary_index.material_sidecars.size();
    graph.texture_candidate_count = count_dds_basenames(primary_index);
    if (!job.package_root.empty()) {
        std::set<std::string> seen_pamts;
        seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
        for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
            const std::string pamt_key = fs::absolute(pamt_path).string();
            if (!seen_pamts.insert(pamt_key).second) continue;
            try {
                const PamtIndex& index = cached_pamt_index(pamt_path);
                ++graph.pamt_count;
                graph.entry_count += index.entry_count;
                graph.material_sidecar_count += index.material_sidecars.size();
                graph.texture_candidate_count += count_dds_basenames(index);
            } catch (...) {
            }
        }
    }
    if (!graph.persistent_cache_hit) {
        std::ostringstream summary;
        summary << "{"
            << "\"version\":" << graph.version << ","
            << "\"key\":\"" << json_escape(graph.key) << "\","
            << "\"root\":\"" << json_escape(root_key) << "\","
            << "\"pamt_count\":" << graph.pamt_count << ","
            << "\"entry_count\":" << graph.entry_count << ","
            << "\"material_sidecar_count\":" << graph.material_sidecar_count << ","
            << "\"texture_candidate_count\":" << graph.texture_candidate_count << ","
            << "\"technique_files\":" << graph.technique_index.files_scanned << ","
            << "\"techniques\":" << graph.technique_index.technique_names.size() << ","
            << "\"texture_parameters\":" << graph.technique_index.texture_parameters
            << "}";
        try {
            write_text(graph.cache_path, summary.str());
        } catch (...) {
        }
    }
    return cache.emplace(key, std::move(graph)).first->second;
}

static const TechniqueParameterInfo* technique_parameter_for_name(
    const TechniqueIndex& index,
    const std::string& parameter_name
) {
    if (parameter_name.empty()) return nullptr;
    auto found = index.parameters_by_name.find(lower_copy(parameter_name));
    if (found == index.parameters_by_name.end()) return nullptr;
    return &found->second;
}

static std::string srgb_mode_for_role(
    const std::string& role,
    const TechniqueParameterInfo* technique_parameter
) {
    if (technique_parameter != nullptr && !technique_parameter->srgb.empty()) {
        const std::string srgb = lower_copy(technique_parameter->srgb);
        if (srgb == "true" || srgb == "1" || srgb == "yes") return "srgb";
        if (srgb == "false" || srgb == "0" || srgb == "no") return "linear";
    }
    return role == "base" ? "srgb" : "linear";
}

static void add_sidecar_texture_ref(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    std::string path,
    std::string parameter,
    const std::string& material_name,
    const std::string& shader_family,
    const std::vector<MaterialParameterRecord>& material_parameters = {}
) {
    std::replace(path.begin(), path.end(), '\\', '/');
    if (lower_copy(path).find(".dds") == std::string::npos) return;
    if (parameter.empty()) parameter = basename_from_path(path);
    const std::string key = lower_copy(path + "|" + parameter + "|" + material_name + "|" + shader_family);
    if (seen.insert(key).second) {
        refs.push_back(SidecarTextureRef{path, parameter, material_name, shader_family, material_parameters});
    }
}

static std::string texture_path_without_known_suffix(const std::string& raw_path) {
    std::string path = raw_path;
    const std::string lower = lower_copy(path);
    for (const std::string& suffix : {"_sp.dds", "_ma.dds", "_mg.dds", "_m.dds", "_n.dds", "_disp.dds"}) {
        if (lower.ends_with(suffix) && path.size() > suffix.size()) {
            path.resize(path.size() - suffix.size());
            path += ".dds";
            return path;
        }
    }
    return "";
}

static bool shader_rule_allows_visible_layer_family(const std::string& shader_family) {
    const std::string rule = shader_rule_for_family(shader_family);
    return rule == "standard" || rule == "standard_v2" || rule == "cloth" || rule == "cloth_v2" || rule == "static_standard" || rule == "static_multitextured";
}

static void add_layer_family_sibling_refs(
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen,
    const std::string& path,
    const std::string& parameter,
    const std::string& material_name,
    const std::string& shader_family,
    const std::vector<MaterialParameterRecord>& material_parameters
) {
    if (!shader_rule_allows_visible_layer_family(shader_family)) return;
    const std::string key = normalized_key(parameter);
    const bool layer_parameter =
        key.find("detail") != std::string::npos
        || key.find("grime") != std::string::npos
        || key.find("dye") != std::string::npos;
    if (!layer_parameter) return;
    const std::string diffuse_path = texture_path_without_known_suffix(path);
    if (diffuse_path.empty() || lower_copy(diffuse_path) == lower_copy(path)) return;
    std::string channel;
    if (!parameter.empty()) {
        const char last = static_cast<char>(std::tolower(static_cast<unsigned char>(parameter.back())));
        if (last == 'r' || last == 'g' || last == 'b' || last == 'a') channel.push_back(last);
    }
    const std::string suffix = channel.empty() ? "" : std::string(1, static_cast<char>(std::toupper(static_cast<unsigned char>(channel.front()))));
    const std::string diffuse_parameter = key.find("grime") != std::string::npos ? ("_grimeDiffuseTexture" + suffix) : ("_detailDiffuseMask" + suffix);
    const std::string normal_parameter = key.find("grime") != std::string::npos ? ("_grimeNormalTexture" + suffix) : ("_detailNormalMask" + suffix);
    const std::string material_parameter = key.find("grime") != std::string::npos ? ("_grimeMaterialTexture" + suffix) : ("_detailMaterialMask" + suffix);
    const std::string height_parameter = "_detailHeightMask" + suffix;
    const std::string stem = diffuse_path.substr(0, diffuse_path.size() - 4);
    add_sidecar_texture_ref(refs, seen, diffuse_path, diffuse_parameter, material_name, shader_family, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_n.dds", normal_parameter, material_name, shader_family, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_sp.dds", material_parameter, material_name, shader_family, material_parameters);
    add_sidecar_texture_ref(refs, seen, stem + "_disp.dds", height_parameter, material_name, shader_family, material_parameters);
}

static void extract_texture_refs_from_scope(
    const std::string& scope_text,
    const std::string& material_name,
    const std::string& shader_family,
    std::vector<SidecarTextureRef>& refs,
    std::set<std::string>& seen
) {
    const std::vector<MaterialParameterRecord> material_parameters = extract_material_parameters(scope_text);
    for (const std::string& tag : collect_xml_tag_blocks(scope_text, "MaterialParameterTexture")) {
        const auto attrs = xml_attribute_map(tag);
        const std::string parameter = xml_attr_value_from_map(attrs, {"_name", "StringItemID", "Name"});
        std::string path = xml_attr_value_from_map(attrs, {"Value", "_path"});
        if (path.empty()) {
            for (const std::string& resource_tag : collect_xml_tag_blocks(tag, "ResourceReferencePath_ITexture")) {
                const auto resource_attrs = xml_attribute_map(resource_tag);
                path = xml_attr_value_from_map(resource_attrs, {"_path", "Value"});
                if (!path.empty()) break;
            }
        }
        add_sidecar_texture_ref(refs, seen, path, parameter, material_name, shader_family, material_parameters);
        add_layer_family_sibling_refs(refs, seen, path, parameter, material_name, shader_family, material_parameters);
    }
}

static int score_material_wrapper_block_for_preview(const std::string& block, const std::string& material_name) {
    const std::string shader_family = extract_shader_family_hint(block);
    const std::string shader_rule = shader_rule_for_family(shader_family);
    const std::string block_lower = lower_copy(block);
    const std::string material_key = normalized_key(material_name);
    int score = 0;
    if (block_lower.find("_basecolortexture") != std::string::npos) score += 180;
    if (block_lower.find("_normaltexture") != std::string::npos) score += 35;
    if (block_lower.find("_materialtexture") != std::string::npos) score += 35;
    if (block_lower.find("_heighttexture") != std::string::npos) score += 18;
    if (block_lower.find("_overlaycolortexture") != std::string::npos && block_lower.find("_basecolortexture") == std::string::npos) score -= 80;
    if (shader_rule == "standard_v2" || shader_rule == "cloth_v2") score += 28;
    else if (shader_rule == "standard" || shader_rule == "cloth" || shader_rule == "skin") score += 22;
    else if (shader_rule == "hair") score -= 35;
    else if (shader_rule == "generic") score -= 55;
    for (const std::string& texture_tag : collect_xml_tag_blocks(block, "MaterialParameterTexture")) {
        const auto attrs = xml_attribute_map(texture_tag);
        std::string path = xml_attr_value_from_map(attrs, {"Value", "_path"});
        if (path.empty()) {
            for (const std::string& resource_tag : collect_xml_tag_blocks(texture_tag, "ResourceReferencePath_ITexture")) {
                const auto resource_attrs = xml_attribute_map(resource_tag);
                path = xml_attr_value_from_map(resource_attrs, {"_path", "Value"});
                if (!path.empty()) break;
            }
        }
        const std::string stem_key = normalized_key(stem_from_path(path));
        if (!material_key.empty() && !stem_key.empty() && (stem_key == material_key || stem_key.find(material_key) != std::string::npos || material_key.find(stem_key) != std::string::npos)) {
            score += 95;
        }
    }
    return score;
}

static std::vector<SidecarTextureRef> extract_sidecar_texture_refs(const std::string& text) {
    std::vector<SidecarTextureRef> refs;
    std::set<std::string> seen;

    std::map<std::string, std::pair<int, std::string>> best_wrapper_by_material;
    for (const std::string& block : collect_xml_tag_blocks(text, "SkinnedMeshMaterialWrapper")) {
        const std::string material_name = xml_attr_value(block, {"_subMeshName", "PrimitiveName", "Name"});
        const std::string key = normalized_key(material_name.empty() ? "default" : material_name);
        const int score = score_material_wrapper_block_for_preview(block, material_name);
        auto found = best_wrapper_by_material.find(key);
        if (found == best_wrapper_by_material.end() || score > found->second.first) {
            best_wrapper_by_material[key] = std::make_pair(score, block);
        }
    }
    for (const auto& item : best_wrapper_by_material) {
        const std::string& block = item.second.second;
        std::string material_name = xml_attr_value(block, {"_subMeshName", "PrimitiveName", "Name"});
        std::replace(material_name.begin(), material_name.end(), '\\', '/');
        const std::string shader_family = extract_shader_family_hint(block);
        extract_texture_refs_from_scope(block, material_name, shader_family, refs, seen);
    }

    if (refs.empty()) {
        for (const std::string& block : collect_xml_tag_blocks(text, "Material")) {
            std::string material_name = xml_attr_value(block, {"PrimitiveName", "_subMeshName", "Name"});
            std::replace(material_name.begin(), material_name.end(), '\\', '/');
            std::string shader_family = extract_shader_family_hint(block);
            if (shader_family.empty()) shader_family = xml_attr_value(block, {"MaterialName", "_materialName"});
            extract_texture_refs_from_scope(block, material_name, shader_family, refs, seen);
        }
    }

    if (refs.empty()) {
        extract_texture_refs_from_scope(text, "", "", refs, seen);
    }

    if (!refs.empty()) return refs;
    for (const std::string& token : extract_dds_tokens(text)) {
        add_sidecar_texture_ref(refs, seen, token, basename_from_path(token), "", "");
    }
    return refs;
}

static std::string extracted_dds_path_for_entry(
    const ArchiveEntryRef& ref,
    const fs::path& cache_root,
    std::vector<std::string>& notes
) {
    if (ref.path.empty() || ref.extension != ".dds") return "";
    if (ref.compressed() && ref.comp_size != ref.orig_size) {
        // Sparse DDS often has the header and first payload bytes stored. Padding
        // is acceptable for preview, but fully compressed entries stay on Python.
    }
    const std::string identity = ref.pamt_path.string() + "|" + ref.path + "|" + std::to_string(ref.offset) + "|" + std::to_string(ref.comp_size) + "|" + std::to_string(ref.orig_size);
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

static int material_match_score(const TextureBinding& binding, const NativeSubmesh& mesh, const std::string& desired_role) {
    int score = 0;
    if (binding.role == desired_role) score += 100;
    if (desired_role == "material" && (binding.role == "detail" || binding.role == "specular")) score += 16;
    if (desired_role == "base" && role_is_technical_for_base(binding.role)) score -= 200;
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

static int material_identity_match_score(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string mesh_text = lower_copy(mesh.material + " " + mesh.name);
    const std::string binding_text = lower_copy(binding.material_name + " " + binding.texture_name + " " + binding.archive_path);
    const std::string mesh_key_a = normalized_material_key(mesh.material);
    const std::string mesh_key_b = normalized_material_key(mesh.name);
    const std::string binding_key = normalized_material_key(binding.material_name);
    int score = 0;
    if (!binding_key.empty() && (!mesh_key_a.empty() || !mesh_key_b.empty())) {
        if (binding_key == mesh_key_a || binding_key == mesh_key_b) score += 160;
        if (!mesh_key_a.empty() && binding_key.find(mesh_key_a) != std::string::npos) score += 72;
        if (!mesh_key_b.empty() && binding_key.find(mesh_key_b) != std::string::npos) score += 72;
        if (!mesh_key_a.empty() && mesh_key_a.find(binding_key) != std::string::npos) score += 54;
        if (!mesh_key_b.empty() && mesh_key_b.find(binding_key) != std::string::npos) score += 54;
        if (score == 0) return 0;
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
    return score;
}

static bool material_identity_requires_exact_path_match(const TextureBinding& binding, const NativeSubmesh& mesh) {
    const std::string binding_material = lower_copy(binding.material_name);
    const std::string mesh_material = lower_copy(mesh.material + " " + mesh.name);
    return binding_material.find(".dds") != std::string::npos && mesh_material.find(".dds") != std::string::npos;
}

static bool support_role_requires_material_scope(const std::string& desired_role) {
    return desired_role == "normal"
        || desired_role == "material"
        || desired_role == "height"
        || desired_role == "specular"
        || desired_role == "detail";
}

static int support_role_identity_threshold(const std::string& desired_role) {
    if (desired_role == "height") return 120;
    if (desired_role == "normal") return 96;
    if (desired_role == "material" || desired_role == "specular") return 88;
    if (desired_role == "detail") return 72;
    return 0;
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
            const bool compatible_material_response = desired_role == "material" && (binding.role == "detail" || binding.role == "specular");
            if (!compatible_material_response) continue;
        }
        const int identity_score = material_identity_match_score(binding, mesh);
        const int identity_threshold = support_role_requires_material_scope(desired_role)
            ? support_role_identity_threshold(desired_role)
            : 0;
        if (
            (material_identity_requires_exact_path_match(binding, mesh) && identity_score < 120)
            || (identity_threshold > 0 && identity_score > 0 && identity_score < identity_threshold)
            || (identity_threshold > 0 && !normalized_material_key(binding.material_name).empty() && identity_score <= 0)
        ) {
            if (rejected_examples != nullptr && rejected_examples->size() < 16) {
                rejected_examples->push_back(
                    desired_role + " rejected cross-slot candidate "
                    + (binding.texture_name.empty() ? basename_from_path(binding.archive_path) : binding.texture_name)
                    + " for " + mesh.material
                    + " identity=" + std::to_string(identity_score)
                );
            }
            continue;
        }
        const int score = material_match_score(binding, mesh, desired_role);
        if (score > best_score) {
            best_score = score;
            best = &binding;
        }
    }
    if (selected_score != nullptr) *selected_score = best == nullptr ? 0 : best_score;
    return best;
}

static const TextureBinding* best_base_binding_for_mode(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const EntryJob& job,
    int* selected_score = nullptr
) {
    const std::string mode = normalize_visible_texture_mode(job.visible_texture_mode);
    const TextureBinding* best = nullptr;
    int best_score = 40;
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty() || binding.role != "base") continue;
        if (technical_for_visible_base(binding.parameter_name, binding.archive_path, binding.role)) continue;
        const bool embedded = binding.source_authority == "embedded_mesh";
        const bool low_authority = low_authority_base_path(binding.archive_path) || low_authority_base_path(binding.texture_name);
        if (!embedded && !visible_class_allowed_for_mode(mode, binding.visible_class)) {
            if (!(mode == "mesh_base_first" && binding.visible_class == "visible_generic")) {
                continue;
            }
        }
        int score = material_match_score(binding, mesh, "base");
        score += visible_class_priority(binding.visible_class) * 18;
        if (embedded) score += mode == "sidecar_visible_first" ? 20 : 120;
        if (binding.source_authority == "exact_sidecar") score += mode == "sidecar_visible_first" ? 95 : 55;
        if (mode == "mesh_base_first") {
            if (!embedded && binding.visible_class == "primary_visible") score += 75;
            if (!embedded && binding.visible_class == "layer_visible") score -= 12;
            if (!embedded && binding.visible_class == "visible_generic") score -= 26;
            if (low_authority) score -= 90;
        } else if (mode == "layer_aware_visible") {
            if (binding.visible_class == "layer_visible") score += 35;
            if (low_authority) score -= 45;
        } else if (mode == "sidecar_visible_first") {
            if (!embedded) score += 65;
            if (binding.visible_class == "layer_visible") score += 22;
            if (low_authority) score -= 35;
        }
        if (score > best_score) {
            best_score = score;
            best = &binding;
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
};

static std::uint64_t g_sidecar_parse_cache_hits = 0;
static std::uint64_t g_sidecar_parse_cache_misses = 0;

static std::uint64_t sidecar_parse_cache_hits() {
    return g_sidecar_parse_cache_hits;
}

static std::uint64_t sidecar_parse_cache_misses() {
    return g_sidecar_parse_cache_misses;
}

static const ParsedMaterialSidecar& cached_parsed_material_sidecar(const ArchiveEntryRef& sidecar) {
    static std::map<std::string, ParsedMaterialSidecar> cache;
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
    parsed.refs = extract_sidecar_texture_refs(sidecar_text);
    if (parsed.refs.empty()) {
        const std::vector<MaterialParameterRecord> material_parameters = extract_material_parameters(sidecar_text);
        for (const std::string& token : extract_dds_tokens(sidecar_text)) {
            parsed.refs.push_back(SidecarTextureRef{token, "", "", parsed.shader_family, material_parameters});
        }
    }
    return cache.emplace(key, std::move(parsed)).first->second;
}

static std::string packed_channels_for_role(const std::string& role, const std::string& name, const std::string& parameter_name) {
    const std::string lower = lower_copy(name + " " + parameter_name);
    if (role == "material") {
        if (lower.find("orm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (lower.find("rma") != std::string::npos) return "r=roughness,g=metalness,b=occlusion";
        if (lower.find("mra") != std::string::npos) return "r=metalness,g=roughness,b=occlusion";
        if (lower.find("arm") != std::string::npos) return "r=occlusion,g=roughness,b=metalness";
        if (lower.find("_ma") != std::string::npos || lower.find("material") != std::string::npos) {
            return "approx:r=occlusion,g=roughness,b=metalness,a=specular";
        }
        if (lower.find("_m") != std::string::npos) return "approx:packed_material_mask";
    }
    if (role == "detail") return "approx:detail/grime/dye mask weights";
    if (role == "specular") return "approx:specular/roughness response";
    if (role == "height") return "height";
    if (role == "normal") return "normal_xy";
    return "";
}

static std::string layer_channel_from_parameter(const std::string& parameter_name) {
    const std::string key = normalized_key(parameter_name);
    if (key.ends_with("r")) return "r";
    if (key.ends_with("g")) return "g";
    if (key.ends_with("b")) return "b";
    if (key.ends_with("a")) return "a";
    return "r";
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
        candidates = {"scratchTintColor" + channel, "tintColor" + channel, "dyeingDetailLayerColorMask" + channel};
    } else if (layer_role == "detail") {
        candidates = {"dyeingDetailLayerColorMask" + channel, "dyeingColorMask" + channel, "tintColor" + channel};
    } else if (layer_role == "overlay") {
        candidates = {"overlayColor", "tintColor" + channel, "tintColor"};
    } else {
        candidates = {"tintColor" + channel, "dyeingColorMask" + channel, "tintColor"};
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
    if (technique_parameter != nullptr && technique_parameter->declared) {
        const std::string declared_type = lower_copy(technique_parameter->type);
        const std::string declared_default = lower_copy(technique_parameter->default_value);
        const bool declared_texture = declared_type.find("texture") != std::string::npos || p.find("texture") != std::string::npos;
        if (declared_texture) {
            if (p.find("normal") != std::string::npos || declared_default.find("0xff7f7f00") != std::string::npos) return "normal";
            if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos) return "height";
            if (p.find("specular") != std::string::npos || p.find("gloss") != std::string::npos || p.find("smoothness") != std::string::npos) return "specular";
            if (p.find("basecolor") != std::string::npos || p.find("diffuse") != std::string::npos || p.find("albedo") != std::string::npos) return "base";
            if (p.find("overlaycolor") != std::string::npos || p.find("layerbasecolor") != std::string::npos || p.find("layercolor") != std::string::npos) return "base";
            if (p.find("mask") != std::string::npos && (p.find("detail") != std::string::npos || p.find("blend") != std::string::npos || p.find("layer") != std::string::npos)) return "detail";
            if (p.find("material") != std::string::npos || p.find("colorblendingmask") != std::string::npos || p == "_masktexture") return "material";
        }
    }
    if (p.find("normal") != std::string::npos || p == "n" || t.find("_n.dds") != std::string::npos) return "normal";
    if (p.find("height") != std::string::npos || p.find("displacement") != std::string::npos || p.find("disp") != std::string::npos || t.find("_disp.dds") != std::string::npos) return "height";
    if (p.find("specular") != std::string::npos || p.find("_sp") != std::string::npos || t.find("_sp.dds") != std::string::npos) return "specular";
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
    if (role == "normal") return "normal";
    if (role == "height") return "height";
    if (role == "specular") return "specular";
    if (role == "detail") return "detail_mask";
    return "packed_material";
}

static void add_sidecar_candidate(
    std::vector<ArchiveEntryRef>& out,
    std::set<std::string>& seen,
    const ArchiveEntryRef& ref
) {
    if (ref.path.empty() || ref.comp_size == 0) return;
    const std::string key = lower_copy(ref.path);
    if (seen.insert(key).second) out.push_back(ref);
}

static void add_sidecar_basename_candidates(
    std::vector<ArchiveEntryRef>& out,
    std::set<std::string>& seen,
    const PamtIndex& index,
    const std::string& basename,
    const std::string& preferred_dir
) {
    auto it = index.by_basename.find(lower_copy(basename));
    if (it == index.by_basename.end()) return;
    std::vector<std::pair<int, ArchiveEntryRef>> scored;
    for (const ArchiveEntryRef& ref : it->second) {
        int score = 10;
        const std::string path = lower_copy(ref.path);
        const std::string dir = lower_copy(dirname_from_path(ref.path));
        if (!preferred_dir.empty() && dir == lower_copy(preferred_dir)) score += 80;
        if (path.find("/modelproperty/") != std::string::npos) score += 30;
        if (path.find("/model/") != std::string::npos) score += 10;
        scored.emplace_back(score, ref);
    }
    std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    for (const auto& item : scored) add_sidecar_candidate(out, seen, item.second);
}

static std::vector<ArchiveEntryRef> lookup_basename_candidates_across_package(
    const EntryJob& job,
    const PamtIndex& primary_index,
    const std::string& basename,
    size_t max_count = 64
) {
    std::vector<ArchiveEntryRef> result;
    std::set<std::string> seen;
    auto add_from_index = [&](const PamtIndex& index) {
        auto found = index.by_basename.find(lower_copy(basename));
        if (found == index.by_basename.end()) return;
        for (const ArchiveEntryRef& ref : found->second) {
            const std::string key = lower_copy(ref.pamt_path.string() + "|" + ref.path);
            if (seen.insert(key).second) result.push_back(ref);
            if (result.size() >= max_count) return;
        }
    };
    add_from_index(primary_index);
    if (result.size() >= max_count || job.package_root.empty()) return result;
    std::set<std::string> seen_pamts;
    seen_pamts.insert(fs::absolute(primary_index.pamt_path).string());
    for (const fs::path& pamt_path : package_root_pamt_paths(job.package_root)) {
        if (result.size() >= max_count) break;
        const std::string pamt_key = fs::absolute(pamt_path).string();
        if (!seen_pamts.insert(pamt_key).second) continue;
        try {
            add_from_index(cached_pamt_index(pamt_path));
        } catch (...) {
        }
    }
    return result;
}

static std::vector<ArchiveEntryRef> material_sidecar_candidates_for_job(
    const EntryJob& job,
    const PamtIndex& index
) {
    std::vector<ArchiveEntryRef> candidates;
    std::set<std::string> seen;
    add_sidecar_candidate(candidates, seen, job.companion_entry);

    const std::string model_stem = stem_from_path(job.path);
    const std::string model_stem_lower = lower_copy(model_stem);
    const std::string model_dir = dirname_from_path(job.path);
    std::vector<std::string> basenames;
    if (job.extension == ".pac") {
        basenames = {model_stem + ".pac_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".prefab", model_stem + ".prefabdata_xml", model_stem + ".meshinfo"};
    } else if (job.extension == ".pam") {
        basenames = {model_stem + ".pami", model_stem + ".pam_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".prefab", model_stem + ".prefabdata_xml", model_stem + ".meshinfo"};
    } else if (job.extension == ".pamlod") {
        basenames = {model_stem + ".pamlod_xml", model_stem + ".pami", model_stem + ".pam_xml", model_stem + ".material", model_stem + ".technique", model_stem + ".prefab", model_stem + ".prefabdata_xml", model_stem + ".meshinfo"};
    }
    for (const std::string& base : basenames) {
        add_sidecar_basename_candidates(candidates, seen, index, base, model_dir);
        for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(job, index, base, 24)) {
            add_sidecar_candidate(candidates, seen, ref);
        }
    }
    if ((job.extension == ".pam" || job.extension == ".pamlod") && !candidates.empty()) {
        return candidates;
    }

    std::vector<std::pair<int, ArchiveEntryRef>> scored;
    const std::string model_dir_lower = lower_copy(model_dir);
    const std::string model_property_dir = lower_copy([&]() {
        std::string converted = model_dir;
        const std::string marker = "/model/";
        const size_t pos = lower_copy(converted).find(marker);
        if (pos != std::string::npos) {
            converted.replace(pos, marker.size(), "/modelproperty/");
        }
        return converted;
    }());
    for (const ArchiveEntryRef& ref : index.material_sidecars) {
        if (seen.find(lower_copy(ref.path)) != seen.end()) continue;
        const std::string ref_stem = lower_copy(stem_from_path(ref.path));
        const std::string ref_path = lower_copy(ref.path);
        const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
        int score = 0;
        if (!model_stem_lower.empty() && ref_stem == model_stem_lower) score += 100;
        if (!model_stem_lower.empty() && ref_path.find(model_stem_lower) != std::string::npos) score += 40;
        if (!model_dir_lower.empty() && ref_dir == model_dir_lower) score += 25;
        if (!model_property_dir.empty() && ref_dir == model_property_dir) score += 45;
        if (ref.extension == ".pami" && (job.extension == ".pam" || job.extension == ".pamlod")) score += 20;
        if ((ref.extension == ".pac_xml" || ref.extension == ".pam_xml" || ref.extension == ".pamlod_xml") && ref_path.find("/modelproperty/") != std::string::npos) score += 15;
        if (score >= 80) scored.emplace_back(score, ref);
    }
    std::sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
        return a.first > b.first;
    });
    for (const auto& item : scored) {
        if (candidates.size() >= 24) break;
        add_sidecar_candidate(candidates, seen, item.second);
    }
    return candidates;
}

static std::vector<TextureBinding> build_material_bindings(
    const EntryJob& job,
    const PamtIndex& index,
    const std::vector<NativeSubmesh>& meshes,
    NativePackage& package
) {
    std::vector<TextureBinding> bindings;
    const NativeMaterialGraph& material_graph = cached_native_material_graph(job, index);
    package.material_graph_status = "active";
    package.material_graph_cache_path = material_graph.cache_path.string();
    package.material_graph_cache_hit = material_graph.persistent_cache_hit;
    package.notes.push_back(
        "native material graph: version=" + std::to_string(material_graph.version) +
        "; cache=" + std::string(material_graph.persistent_cache_hit ? "hit" : "write") +
        "; pamts=" + std::to_string(material_graph.pamt_count) +
        "; entries=" + std::to_string(material_graph.entry_count) +
        "; sidecars=" + std::to_string(material_graph.material_sidecar_count) +
        "; dds_basenames=" + std::to_string(material_graph.texture_candidate_count)
    );
    const std::vector<ArchiveEntryRef> sidecars = material_sidecar_candidates_for_job(job, index);
    if (sidecars.empty()) {
        package.material_index = "native_index_no_sidecar";
        package.texture_resolution = "none";
        package.notes.push_back("native material index: no matching .pac_xml/.pam_xml/.pamlod_xml/.pami/.material/.technique/.prefab sidecar");
        return bindings;
    }
    const TechniqueIndex& technique_index = material_graph.technique_index;
    if (technique_index.files_scanned > 0) {
        package.notes.push_back(
            "native technique index: files=" + std::to_string(technique_index.files_scanned) +
            "; techniques=" + std::to_string(technique_index.technique_names.size()) +
            "; texture_params=" + std::to_string(technique_index.texture_parameters)
        );
    }
    std::vector<std::string> notes;
    std::set<std::string> seen_bindings;
    std::set<std::string> sidecar_kinds;
    std::set<std::string> shader_rules;
    for (const ArchiveEntryRef& sidecar : sidecars) {
        add_asset_family_row(package, NativeAssetFamilyRow{
            "Material",
            sidecar.extension == ".pami" ? "Material Index" : "Material Sidecar",
            sidecar.basename.empty() ? basename_from_path(sidecar.path) : sidecar.basename,
            sidecar.path,
            "Resolved",
            "Sidecar",
            "authoritative",
            "required",
            "Native preview-core selected this material sidecar for the current model.",
            "metadata",
            "Material sidecar",
            "",
            "",
            "",
            package_label_for_ref(sidecar),
            sidecar.extension,
            "",
            "",
            "",
            ""
        });
        const ParsedMaterialSidecar* parsed_sidecar = nullptr;
        try {
            parsed_sidecar = &cached_parsed_material_sidecar(sidecar);
        } catch (const std::exception& exc) {
            package.notes.push_back(std::string("native material sidecar read failed:") + sidecar.path + ": " + exc.what());
            continue;
        }
        if (parsed_sidecar == nullptr) continue;
        const std::string& sidecar_shader_family = parsed_sidecar->shader_family;
        const std::string& sidecar_shader_rule = parsed_sidecar->shader_rule;
        const SidecarParameterSummary& parameter_summary = parsed_sidecar->parameter_summary;
        shader_rules.insert(sidecar_shader_rule);
        sidecar_kinds.insert(sidecar.extension.empty() ? "unknown" : sidecar.extension);
        package.notes.push_back(
            "native material sidecar: " + sidecar.path +
            "; rule=" + sidecar_shader_rule +
            "; texture_params=" + std::to_string(parameter_summary.texture_params) +
            "; float_params=" + std::to_string(parameter_summary.float_params) +
            "; color_params=" + std::to_string(parameter_summary.color_params) +
            "; byte4_params=" + std::to_string(parameter_summary.byte4_params) +
            "; flags=" + std::to_string(parameter_summary.bit_flags)
        );
        const std::vector<SidecarTextureRef>& refs = parsed_sidecar->refs;
        int refs_considered = 0;
        for (const SidecarTextureRef& texture_ref : refs) {
            const std::string ref_material_key = normalized_material_key(texture_ref.material_name);
            if (!ref_material_key.empty() && !meshes.empty()) {
                bool matched_mesh = false;
                for (const NativeSubmesh& mesh : meshes) {
                    const std::string mesh_material_key = normalized_material_key(mesh.material);
                    const std::string mesh_name_key = normalized_material_key(mesh.name);
                    if (
                        (!mesh_material_key.empty() && (ref_material_key == mesh_material_key || ref_material_key.find(mesh_material_key) != std::string::npos || mesh_material_key.find(ref_material_key) != std::string::npos))
                        || (!mesh_name_key.empty() && (ref_material_key == mesh_name_key || ref_material_key.find(mesh_name_key) != std::string::npos || mesh_name_key.find(ref_material_key) != std::string::npos))
                    ) {
                        matched_mesh = true;
                        break;
                    }
                }
                if (!matched_mesh) {
                    if (package.rejected_texture_examples.size() < 16) {
                        package.rejected_texture_examples.push_back(
                            "sidecar skipped unrelated material wrapper "
                            + (texture_ref.material_name.empty() ? std::string("-") : texture_ref.material_name)
                            + " texture="
                            + basename_from_path(texture_ref.path)
                        );
                    }
                    continue;
                }
            }
            ++refs_considered;
            const std::string base = lower_copy(basename_from_path(texture_ref.path));
            std::vector<ArchiveEntryRef> texture_candidates = lookup_basename_candidates_across_package(job, index, base, 96);
            if (texture_candidates.empty()) {
                continue;
            }
            const ArchiveEntryRef* selected = nullptr;
            int best_score = -100000;
            const std::string sidecar_dir = lower_copy(dirname_from_path(sidecar.path));
            for (const ArchiveEntryRef& ref : texture_candidates) {
                int score = 10;
                const std::string ref_path = lower_copy(ref.path);
                const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
                if (lower_copy(ref.basename) == base) score += 30;
                if (!sidecar_dir.empty() && ref_dir == sidecar_dir) score += 50;
                if (ref_path.find("/texture/") != std::string::npos) score += 20;
                if (ref_path.find("/modelproperty/") != std::string::npos) score += 5;
                if (ref.pamt_path == sidecar.pamt_path) score += 8;
                if (score > best_score) {
                    best_score = score;
                    selected = &ref;
                }
            }
            if (selected == nullptr && !texture_candidates.empty()) selected = &texture_candidates.front();
            if (selected == nullptr) continue;
            const std::string extracted = extracted_dds_path_for_entry(*selected, job.cache_root, notes);
            if (extracted.empty()) continue;
            std::string shader_family = texture_ref.shader_family.empty() ? sidecar_shader_family : texture_ref.shader_family;
            if (shader_family.empty() && sidecar.extension == ".pami") shader_family = "StaticMaterial";
            const std::string shader_rule = shader_rule_for_family(shader_family);
            const TechniqueParameterInfo* technique_parameter = technique_parameter_for_name(technique_index, texture_ref.parameter_name);
            TextureBinding binding;
            binding.role = role_from_parameter_shader_and_name(texture_ref.parameter_name, shader_rule, base, technique_parameter);
            binding.source_path = extracted;
            binding.archive_path = selected->path;
            binding.texture_name = selected->basename;
            const DdsHeaderInfo dds_info = inspect_dds_header_file(extracted);
            binding.dds_width = dds_info.width;
            binding.dds_height = dds_info.height;
            binding.dds_format = dds_info.format;
            binding.parameter_name = texture_ref.parameter_name.empty() ? base : texture_ref.parameter_name;
            const std::string parameter_lower = lower_copy(binding.parameter_name);
            if (binding.role == "base" && role_is_technical_for_base(texture_role_from_name(base))) {
                binding.role = texture_role_from_name(base);
            }
            binding.semantic_type = semantic_type_for_role(binding.role);
            binding.semantic_subtype = semantic_subtype_for_role(binding.role);
            binding.shader_family = shader_family;
            binding.shader_rule = shader_rule;
            binding.material_name = texture_ref.material_name.empty() ? stem_from_path(sidecar.path) : texture_ref.material_name;
            binding.sidecar_path = sidecar.path;
            binding.sidecar_kind = sidecar.extension;
            binding.linked_mesh_path = parameter_summary.linked_mesh_path;
            binding.packed_channels = packed_channels_for_role(binding.role, base, parameter_lower);
            binding.srgb_mode = srgb_mode_for_role(binding.role, technique_parameter);
            binding.parameter_declared_by = technique_parameter != nullptr ? "technique" : "";
            binding.visible_class = visible_class_for_binding(binding.parameter_name, binding.archive_path, binding.role);
            binding.source_authority = "sidecar";
            binding.relation_confidence = (!texture_ref.parameter_name.empty() && !texture_ref.material_name.empty()) ? "authoritative" : "derived_same_stem";
            binding.relation_reason = texture_ref.parameter_name.empty()
                ? "Resolved by native texture basename/family lookup."
                : "Resolved from native material sidecar texture parameter.";
            binding.layer_role = layer_role_from_parameter(binding.parameter_name, binding.role);
            binding.layer_channel = layer_channel_from_parameter(binding.parameter_name);
            binding.layer_weight = layer_weight_from_parameters(texture_ref.material_parameters, binding.layer_role, binding.layer_channel);
            binding.tint_color = tint_for_layer(texture_ref.material_parameters, binding.layer_role, binding.layer_channel);
            binding.blend_flags = normalized_key(binding.parameter_name).find("colorblending") != std::string::npos ? "color_blending_mask" : "";
            binding.material_parameter_names = joined_parameter_names(texture_ref.material_parameters);
            binding.roughness_hint = std::clamp(scalar_parameter_hint(texture_ref.material_parameters, {"roughness", "scratchRoughness"}, 0.0f), 0.0f, 1.0f);
            binding.metalness_hint = std::clamp(scalar_parameter_hint(texture_ref.material_parameters, {"metallic", "metalness", "scratchMetallic"}, 0.0f), 0.0f, 1.0f);
            binding.specular_hint = std::clamp(scalar_parameter_hint(texture_ref.material_parameters, {"specular", "specularAmount"}, 0.0f), 0.0f, 1.0f);
            binding.height_scale_hint = std::clamp(scalar_parameter_hint(texture_ref.material_parameters, {"screenSpaceDisplacementScale", "detailScreenSpaceDisplacementScale", "heightIntensity"}, 0.0f), 0.0f, 1.0f);
            if (binding.role == "base" && role_is_technical_for_base(texture_role_from_name(base))) {
                binding.material_output_quality = "approximate";
            } else if (technique_parameter != nullptr && !texture_ref.parameter_name.empty() && !texture_ref.material_name.empty()) {
                binding.material_output_quality = "exact";
            } else if (!texture_ref.parameter_name.empty() && !texture_ref.material_name.empty()) {
                binding.material_output_quality = "exact";
            } else {
                binding.material_output_quality = "inferred";
            }
            if (binding.material_output_quality == "exact") binding.source_authority = "exact_sidecar";
            binding.evidence_grade = evidence_grade_for_binding(binding, technique_parameter);
            const std::string binding_key = lower_copy(binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name);
            if (seen_bindings.insert(binding_key).second) {
                bindings.push_back(binding);
                add_asset_family_row(package, NativeAssetFamilyRow{
                    "Textures",
                    "Texture",
                    selected->basename.empty() ? basename_from_path(selected->path) : selected->basename,
                    selected->path,
                    "Resolved",
                    (!texture_ref.parameter_name.empty() ? "Sidecar" : "Family"),
                    binding.relation_confidence,
                    "required",
                    binding.relation_reason,
                    "texture",
                    binding.semantic_type.empty() ? binding.role : binding.semantic_type,
                    binding.parameter_name,
                    binding.parameter_name,
                    binding.material_name,
                    package_label_for_ref(*selected),
                    sidecar.extension,
                    binding.shader_family,
                    binding.role,
                    "",
                    ""
                });
            }
        }
        package.dds_candidates += refs_considered;
    }
    package.dds_extracted = static_cast<int>(bindings.size());
    int exact_bindings = 0;
    int inferred_bindings = 0;
    int approximate_bindings = 0;
    for (const TextureBinding& binding : bindings) {
        if (binding.material_output_quality == "exact") ++exact_bindings;
        else if (binding.material_output_quality == "approximate") ++approximate_bindings;
        else ++inferred_bindings;
    }
    std::ostringstream kind_summary;
    bool first_kind = true;
    for (const std::string& kind : sidecar_kinds) {
        if (!first_kind) kind_summary << "+";
        first_kind = false;
        kind_summary << kind;
    }
    std::ostringstream rule_summary;
    bool first_rule = true;
    for (const std::string& rule : shader_rules) {
        if (!first_rule) rule_summary << "+";
        first_rule = false;
        rule_summary << rule;
    }
    package.material_index = bindings.empty() ? "native_sidecars_no_resolved_dds" : ("native_sidecar_index:" + kind_summary.str());
    package.texture_resolution = bindings.empty() ? "none" : "same_pamt_basename";
    package.material_output_quality = bindings.empty()
        ? "approximate"
        : (exact_bindings > 0 ? "exact_inputs_inferred_shader" : "inferred");
    package.notes.push_back(
        std::string("native material accuracy: ") + package.material_output_quality +
        "; sidecars=" + std::to_string(sidecars.size()) +
        "; shader_rules=" + (rule_summary.str().empty() ? "generic" : rule_summary.str()) +
        "; bindings exact=" + std::to_string(exact_bindings) +
        " inferred=" + std::to_string(inferred_bindings) +
        " approximate=" + std::to_string(approximate_bindings)
    );
    for (const std::string& note : notes) {
        package.notes.push_back(note);
    }
    return bindings;
}

static void append_mesh_reference_bindings(
    const EntryJob& job,
    const PamtIndex& index,
    const std::vector<NativeSubmesh>& meshes,
    std::vector<TextureBinding>& bindings,
    NativePackage& package
) {
    std::set<std::string> seen;
    for (const TextureBinding& binding : bindings) {
        seen.insert(lower_copy(binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name));
    }
    std::vector<std::string> notes;
    for (const NativeSubmesh& mesh : meshes) {
        std::vector<std::string> raw_names = {mesh.material, mesh.name};
        for (const std::string& raw_name : raw_names) {
            std::string stem = stem_from_path(raw_name);
            if (stem.empty()) stem = raw_name;
            if (stem.empty()) continue;
            const std::string basename = lower_copy(stem) + ".dds";
            std::vector<ArchiveEntryRef> candidates = lookup_basename_candidates_across_package(job, index, basename, 32);
            if (candidates.empty()) continue;
            const ArchiveEntryRef* selected = nullptr;
            int best_score = -100000;
            const std::string model_dir = lower_copy(dirname_from_path(job.path));
            for (const ArchiveEntryRef& ref : candidates) {
                int score = 20;
                const std::string ref_path = lower_copy(ref.path);
                const std::string ref_dir = lower_copy(dirname_from_path(ref.path));
                if (ref.extension == ".dds") score += 40;
                if (!model_dir.empty() && ref_dir == model_dir) score += 30;
                if (ref_path.find("/texture/") != std::string::npos) score += 18;
                if (lower_copy(stem_from_path(ref.path)) == lower_copy(stem)) score += 60;
                if (score > best_score) {
                    best_score = score;
                    selected = &ref;
                }
            }
            if (selected == nullptr || selected->extension != ".dds") continue;
            const std::string extracted = extracted_dds_path_for_entry(*selected, job.cache_root, notes);
            if (extracted.empty()) continue;
            TextureBinding binding;
            binding.role = texture_role_from_name(selected->basename);
            binding.source_path = extracted;
            binding.archive_path = selected->path;
            binding.texture_name = selected->basename;
            binding.parameter_name = "embedded_mesh_reference";
            binding.semantic_type = semantic_type_for_role(binding.role);
            binding.semantic_subtype = semantic_subtype_for_role(binding.role);
            binding.shader_family = "";
            binding.shader_rule = "embedded_mesh";
            binding.material_name = mesh.material.empty() ? mesh.name : mesh.material;
            binding.sidecar_path = "";
            binding.sidecar_kind = "embedded_mesh";
            binding.linked_mesh_path = job.path;
            binding.packed_channels = packed_channels_for_role(binding.role, binding.texture_name, binding.parameter_name);
            binding.srgb_mode = srgb_mode_for_role(binding.role, nullptr);
            binding.parameter_declared_by = "mesh";
            binding.visible_class = visible_class_for_binding(binding.parameter_name, binding.archive_path, binding.role);
            binding.source_authority = "embedded_mesh";
            binding.relation_confidence = role_is_technical_for_base(binding.role) ? "derived_same_stem" : "exact_path";
            binding.relation_reason = role_is_technical_for_base(binding.role)
                ? "Embedded mesh reference resolved to a technical/support texture."
                : "Embedded mesh material/base name resolved directly to DDS.";
            const DdsHeaderInfo dds_info = inspect_dds_header_file(extracted);
            binding.dds_width = dds_info.width;
            binding.dds_height = dds_info.height;
            binding.dds_format = dds_info.format;
            binding.material_output_quality = role_is_technical_for_base(binding.role) ? "inferred" : "exact";
            const std::string key = lower_copy(binding.role + "|" + binding.archive_path + "|" + binding.parameter_name + "|" + binding.material_name);
            if (!seen.insert(key).second) continue;
            bindings.push_back(binding);
            add_asset_family_row(package, NativeAssetFamilyRow{
                "Textures",
                "Texture",
                selected->basename.empty() ? basename_from_path(selected->path) : selected->basename,
                selected->path,
                "Resolved",
                "Embedded Mesh",
                binding.relation_confidence,
                role_is_technical_for_base(binding.role) ? "manual" : "required",
                binding.relation_reason,
                "texture",
                binding.semantic_type,
                binding.parameter_name,
                binding.parameter_name,
                binding.material_name,
                package_label_for_ref(*selected),
                "embedded_mesh",
                binding.shader_family,
                binding.role,
                "",
                ""
            });
        }
    }
    for (const std::string& note : notes) {
        package.notes.push_back(note);
    }
}

static std::array<float, 3> color_for_batch(int index) {
    static const std::array<std::array<float, 3>, 8> colors = {{
        {0.78f, 0.62f, 0.44f},
        {0.58f, 0.68f, 0.78f},
        {0.68f, 0.55f, 0.44f},
        {0.64f, 0.64f, 0.56f},
        {0.55f, 0.72f, 0.62f},
        {0.76f, 0.58f, 0.62f},
        {0.62f, 0.60f, 0.78f},
        {0.72f, 0.70f, 0.60f},
    }};
    return colors[static_cast<size_t>(std::max(0, index)) % colors.size()];
}

static void append_float(std::vector<char>& out, float value) {
    const char* bytes = reinterpret_cast<const char*>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(float));
}

static void append_int32(std::vector<char>& out, std::int32_t value) {
    const char* bytes = reinterpret_cast<const char*>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(std::int32_t));
}

static void write_geometry_blob(
    const fs::path& geometry_path,
    const fs::path& identity_path,
    const NativeSubmesh& mesh,
    const Vec3& center,
    float scale,
    const std::array<float, 3>& color
) {
    std::vector<Vec3> tangents(mesh.positions.size());
    std::vector<Vec3> bitangents(mesh.positions.size());
    for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
        const std::uint32_t i0 = mesh.indices[i];
        const std::uint32_t i1 = mesh.indices[i + 1];
        const std::uint32_t i2 = mesh.indices[i + 2];
        if (i0 >= mesh.positions.size() || i1 >= mesh.positions.size() || i2 >= mesh.positions.size()) continue;
        const Vec3 p0 = mesh.positions[i0];
        const Vec3 p1 = mesh.positions[i1];
        const Vec3 p2 = mesh.positions[i2];
        const Vec2 uv0 = i0 < mesh.uvs.size() ? mesh.uvs[i0] : Vec2{};
        const Vec2 uv1 = i1 < mesh.uvs.size() ? mesh.uvs[i1] : Vec2{};
        const Vec2 uv2 = i2 < mesh.uvs.size() ? mesh.uvs[i2] : Vec2{};
        const Vec3 e1 = vec_sub(p1, p0);
        const Vec3 e2 = vec_sub(p2, p0);
        const float du1 = uv1.x - uv0.x;
        const float dv1 = uv1.y - uv0.y;
        const float du2 = uv2.x - uv0.x;
        const float dv2 = uv2.y - uv0.y;
        const float denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) < 1.0e-8f) continue;
        const float r = 1.0f / denom;
        const Vec3 tangent = vec_mul(vec_sub(vec_mul(e1, dv2), vec_mul(e2, dv1)), r);
        const Vec3 bitangent = vec_mul(vec_sub(vec_mul(e2, du1), vec_mul(e1, du2)), r);
        tangents[i0] = vec_add(tangents[i0], tangent);
        tangents[i1] = vec_add(tangents[i1], tangent);
        tangents[i2] = vec_add(tangents[i2], tangent);
        bitangents[i0] = vec_add(bitangents[i0], bitangent);
        bitangents[i1] = vec_add(bitangents[i1], bitangent);
        bitangents[i2] = vec_add(bitangents[i2], bitangent);
    }

    std::vector<char> geometry;
    std::vector<char> identity;
    geometry.reserve(mesh.indices.size() * 23u * 4u);
    identity.reserve(mesh.indices.size() * 8u);
    for (size_t tri = 0; tri + 2 < mesh.indices.size(); tri += 3) {
        const std::uint32_t indices[3] = {mesh.indices[tri], mesh.indices[tri + 1], mesh.indices[tri + 2]};
        for (int corner = 0; corner < 3; ++corner) {
            const std::uint32_t vi = indices[corner];
            const Vec3 raw_position = mesh.positions[vi];
            const Vec3 position = vec_mul(vec_sub(raw_position, center), scale);
            const Vec3 normal = vec_normalize(vi < mesh.normals.size() ? mesh.normals[vi] : Vec3{0.0f, 1.0f, 0.0f});
            Vec3 tangent = vec_normalize(vi < tangents.size() ? tangents[vi] : Vec3{}, Vec3{});
            Vec3 bitangent = vec_normalize(vi < bitangents.size() ? bitangents[vi] : Vec3{}, Vec3{});
            if (vec_dot(tangent, tangent) <= 1.0e-8f) {
                const Vec3 up = std::abs(normal.y) < 0.9f ? Vec3{0.0f, 1.0f, 0.0f} : Vec3{1.0f, 0.0f, 0.0f};
                tangent = vec_normalize(vec_cross(up, normal), Vec3{1.0f, 0.0f, 0.0f});
            }
            if (vec_dot(bitangent, bitangent) <= 1.0e-8f) {
                bitangent = vec_normalize(vec_cross(normal, tangent), Vec3{0.0f, 0.0f, 1.0f});
            }
            const Vec2 uv = vi < mesh.uvs.size() ? mesh.uvs[vi] : Vec2{};
            const std::int32_t source_vertex = vi < mesh.source_vertex_indices.size()
                ? mesh.source_vertex_indices[vi]
                : static_cast<std::int32_t>(vi);
            const float bary[3] = {corner == 0 ? 1.0f : 0.0f, corner == 1 ? 1.0f : 0.0f, corner == 2 ? 1.0f : 0.0f};
            for (float value : {
                position.x, position.y, position.z,
                normal.x, normal.y, normal.z,
                color[0], color[1], color[2],
                uv.x, uv.y,
                tangent.x, tangent.y, tangent.z,
                bitangent.x, bitangent.y, bitangent.z,
                normal.x, normal.y, normal.z,
                bary[0], bary[1], bary[2],
            }) {
                append_float(geometry, value);
            }
            append_int32(identity, static_cast<std::int32_t>(mesh.source_submesh_index));
            append_int32(identity, source_vertex);
        }
    }
    write_binary(geometry_path, geometry);
    write_binary(identity_path, identity);
}

static std::string dds_entry_json(const TextureBinding* binding, const std::string& slot) {
    if (binding == nullptr || binding->source_path.empty()) return "";
    std::ostringstream out;
    out << "\"" << json_escape(slot) << "\":{"
        << "\"slot\":\"" << json_escape(slot) << "\","
        << "\"source_path\":\"" << json_escape(binding->source_path) << "\","
        << "\"archive_path\":\"" << json_escape(binding->archive_path) << "\","
        << "\"parameter_name\":\"" << json_escape(binding->parameter_name) << "\","
        << "\"semantic_type\":\"" << json_escape(binding->semantic_type) << "\","
        << "\"semantic_subtype\":\"" << json_escape(binding->semantic_subtype) << "\","
        << "\"shader_family\":\"" << json_escape(binding->shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(binding->shader_rule) << "\","
        << "\"sidecar_path\":\"" << json_escape(binding->sidecar_path) << "\","
        << "\"sidecar_kind\":\"" << json_escape(binding->sidecar_kind) << "\","
        << "\"linked_mesh_path\":\"" << json_escape(binding->linked_mesh_path) << "\","
        << "\"packed_channels\":\"" << json_escape(binding->packed_channels) << "\","
        << "\"srgb_mode\":\"" << json_escape(binding->srgb_mode) << "\","
        << "\"parameter_declared_by\":\"" << json_escape(binding->parameter_declared_by) << "\","
        << "\"material_output_quality\":\"" << json_escape(binding->material_output_quality) << "\","
        << "\"width\":" << binding->dds_width << ","
        << "\"height\":" << binding->dds_height << ","
        << "\"format\":\"" << json_escape(binding->dds_format) << "\","
        << "\"available\":true,"
        << "\"direct_upload_candidate\":true"
        << "}";
    return out.str();
}

static std::string batch_stem(size_t batch_index) {
    std::ostringstream out;
    out << "batch_" << std::setw(3) << std::setfill('0') << batch_index;
    return out.str();
}

static std::vector<const TextureBinding*> relevant_bindings_for_mesh(
    const std::vector<TextureBinding>& bindings,
    const NativeSubmesh& mesh,
    const std::vector<const TextureBinding*>& selected_slots
) {
    std::vector<const TextureBinding*> result;
    std::set<const TextureBinding*> seen;
    auto add = [&](const TextureBinding* binding) {
        if (binding != nullptr && seen.insert(binding).second) result.push_back(binding);
    };
    for (const TextureBinding* binding : selected_slots) add(binding);
    if (bindings.size() <= 8) {
        std::set<std::string> scoped_materials;
        for (const TextureBinding& binding : bindings) {
            const std::string key = normalized_material_key(binding.material_name);
            if (!key.empty()) scoped_materials.insert(key);
        }
        if (scoped_materials.size() <= 1) {
            for (const TextureBinding& binding : bindings) add(&binding);
            return result;
        }
        for (const TextureBinding& binding : bindings) {
            if (material_identity_match_score(binding, mesh) >= 120) add(&binding);
        }
        return result;
    }
    for (const TextureBinding& binding : bindings) {
        if (binding.source_path.empty()) continue;
        const int score = material_identity_match_score(binding, mesh);
        const int threshold = normalized_material_key(binding.material_name).empty() ? 42 : 120;
        if (score >= threshold) add(&binding);
    }
    return result;
}

struct NativeMaterialHints {
    float roughness = 0.45f;
    float metalness = 0.0f;
    float specular = 0.45f;
    float height_scale = 0.35f;
};

static NativeMaterialHints material_hints_for_bindings(const std::vector<const TextureBinding*>& bindings) {
    NativeMaterialHints hints;
    bool has_skin = false;
    bool has_hair = false;
    bool has_standard_v2 = false;
    bool has_static_multi = false;
    bool has_specular = false;
    bool has_material_mask = false;
    bool has_height = false;
    bool has_metal = false;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string rule = lower_copy(binding->shader_rule);
        const std::string packed = lower_copy(binding->packed_channels + " " + binding->parameter_name);
        has_skin = has_skin || rule == "skin";
        has_hair = has_hair || rule == "hair";
        has_standard_v2 = has_standard_v2 || rule == "standard_v2";
        has_static_multi = has_static_multi || rule == "static_multitextured";
        has_specular = has_specular || binding->role == "specular";
        has_material_mask = has_material_mask || binding->role == "material" || binding->role == "detail";
        has_height = has_height || binding->role == "height";
        has_metal = has_metal || packed.find("metal") != std::string::npos;
    }
    if (has_skin) {
        hints.roughness = 0.56f;
        hints.specular = 0.28f;
        hints.height_scale = 0.18f;
    } else if (has_hair) {
        hints.roughness = 0.38f;
        hints.specular = 0.58f;
        hints.height_scale = 0.14f;
    } else if (has_standard_v2) {
        hints.roughness = has_material_mask ? 0.42f : 0.50f;
        hints.specular = has_specular ? 0.56f : 0.38f;
        hints.metalness = has_metal ? 0.10f : 0.0f;
        hints.height_scale = has_height ? 0.34f : 0.0f;
    } else if (has_static_multi) {
        hints.roughness = 0.58f;
        hints.specular = has_specular ? 0.30f : 0.18f;
        hints.height_scale = has_height ? 0.24f : 0.0f;
    } else {
        hints.specular = has_specular ? 0.42f : 0.20f;
        hints.height_scale = has_height ? 0.28f : 0.0f;
    }
    return hints;
}

static bool binding_is_layer_diffuse(const TextureBinding& binding, const TextureBinding* selected_base) {
    if (binding.role != "base") return false;
    if (&binding == selected_base) return false;
    const std::string role = lower_copy(binding.layer_role);
    if (role == "detail" || role == "grime" || role == "damage" || role == "overlay" || role == "layer") return true;
    if (binding.visible_class == "layer_visible") return true;
    const std::string parameter = normalized_key(binding.parameter_name);
    return parameter.find("detaildiffuse") != std::string::npos
        || parameter.find("grimediffuse") != std::string::npos
        || parameter.find("colortexture") != std::string::npos;
}

static bool shader_rule_holds_layer_albedo(const std::vector<const TextureBinding*>& bindings) {
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr) continue;
        const std::string rule = lower_copy(binding->shader_rule + " " + binding->shader_family);
        if (
            rule.find("skin") != std::string::npos
            || rule.find("wrinkle") != std::string::npos
            || rule.find("hair") != std::string::npos
        ) {
            return true;
        }
    }
    return false;
}

static bool layer_channel_matches(const TextureBinding& binding, const std::string& channel) {
    return binding.layer_channel.empty() || channel.empty() || binding.layer_channel == channel;
}

static const TextureBinding* find_layer_aux_binding(
    const std::vector<const TextureBinding*>& bindings,
    const std::string& desired_role,
    const std::string& layer_role,
    const std::string& channel
) {
    const TextureBinding* best = nullptr;
    int best_score = -1000;
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr || binding->source_path.empty()) continue;
        int score = -1000;
        const std::string parameter = normalized_key(binding->parameter_name);
        const std::string binding_layer = lower_copy(binding->layer_role);
        if (desired_role == "mask") {
            if (layer_role == "detail" && (parameter.find("detailmask") != std::string::npos || binding->role == "detail")) score = 120;
            else if ((layer_role == "grime" || layer_role == "layer") && (parameter.find("colorblendingmask") != std::string::npos || parameter.find("blendingmask") != std::string::npos)) score = 118;
            else if (layer_role == "damage" && parameter.find("mask") != std::string::npos) score = 104;
            else if (binding->role == "detail") score = 42;
        } else if (desired_role == "normal") {
            if (binding->role == "normal") score = 72;
            if (parameter.find(layer_role + "normal") != std::string::npos) score += 60;
            if (parameter.find("detailnormal") != std::string::npos && layer_role == "detail") score += 60;
            if (parameter.find("grimenormal") != std::string::npos && layer_role == "grime") score += 60;
        } else if (desired_role == "material") {
            if (binding->role == "material" || binding->role == "specular") score = 62;
            if (parameter.find(layer_role + "material") != std::string::npos) score += 64;
            if (parameter.find("detailmaterial") != std::string::npos && layer_role == "detail") score += 64;
            if (parameter.find("grimematerial") != std::string::npos && layer_role == "grime") score += 64;
        } else if (desired_role == "height") {
            if (binding->role == "height") score = 52;
            if (parameter.find(layer_role + "height") != std::string::npos) score += 66;
            if (parameter.find("detailheight") != std::string::npos && layer_role == "detail") score += 66;
        }
        if (score <= -1000) continue;
        if (binding_layer == layer_role) score += 18;
        if (layer_channel_matches(*binding, channel)) score += 24;
        else score -= 18;
        if (score > best_score) {
            best_score = score;
            best = binding;
        }
    }
    return best_score >= 40 ? best : nullptr;
}

static MaterialLayer make_base_material_layer(
    const TextureBinding* base,
    const TextureBinding* normal,
    const TextureBinding* material,
    const TextureBinding* height,
    const TextureBinding* specular,
    const NativeMaterialHints& hints
) {
    MaterialLayer layer;
    layer.layer_role = "base";
    layer.layer_channel = "r";
    layer.shader_family = base != nullptr ? base->shader_family : "";
    layer.shader_rule = base != nullptr ? base->shader_rule : "";
    layer.evidence_grade = base != nullptr ? base->evidence_grade : "approximate";
    layer.weight = 1.0f;
    layer.roughness_hint = hints.roughness;
    layer.metalness_hint = hints.metalness;
    layer.specular_hint = hints.specular;
    layer.height_scale_hint = hints.height_scale;
    if (base != nullptr) {
        layer.diffuse_source = base->source_path;
        layer.diffuse_archive_path = base->archive_path;
        layer.source_parameter = base->parameter_name;
        layer.tint = base->tint_color;
    }
    if (normal != nullptr) {
        layer.normal_source = normal->source_path;
        layer.normal_archive_path = normal->archive_path;
    }
    const TextureBinding* material_response = material != nullptr ? material : specular;
    if (material_response != nullptr) {
        layer.material_source = material_response->source_path;
        layer.material_archive_path = material_response->archive_path;
    }
    if (height != nullptr) {
        layer.height_source = height->source_path;
        layer.height_archive_path = height->archive_path;
    }
    return layer;
}

static std::vector<MaterialLayer> compile_material_layers(
    const std::vector<const TextureBinding*>& bindings,
    const TextureBinding* base,
    const TextureBinding* normal,
    const TextureBinding* material,
    const TextureBinding* height,
    const TextureBinding* specular,
    const NativeMaterialHints& hints
) {
    std::vector<MaterialLayer> layers;
    layers.push_back(make_base_material_layer(base, normal, material, height, specular, hints));
    if (shader_rule_holds_layer_albedo(bindings)) {
        return layers;
    }
    for (const TextureBinding* binding : bindings) {
        if (binding == nullptr || !binding_is_layer_diffuse(*binding, base)) continue;
        MaterialLayer layer;
        layer.layer_role = binding->layer_role.empty() || binding->layer_role == "base" ? "layer" : binding->layer_role;
        layer.layer_channel = binding->layer_channel.empty() ? "r" : binding->layer_channel;
        layer.shader_family = binding->shader_family;
        layer.shader_rule = binding->shader_rule;
        layer.evidence_grade = binding->evidence_grade;
        layer.weight = std::clamp(binding->layer_weight, 0.0f, 1.0f);
        if (layer.weight <= 0.001f) layer.weight = 0.28f;
        layer.tint = binding->tint_color;
        layer.diffuse_source = binding->source_path;
        layer.diffuse_archive_path = binding->archive_path;
        layer.source_parameter = binding->parameter_name;
        layer.blend_order = "base_then_" + layer.layer_role;
        const TextureBinding* mask = find_layer_aux_binding(bindings, "mask", layer.layer_role, layer.layer_channel);
        const TextureBinding* layer_normal = find_layer_aux_binding(bindings, "normal", layer.layer_role, layer.layer_channel);
        const TextureBinding* layer_material = find_layer_aux_binding(bindings, "material", layer.layer_role, layer.layer_channel);
        const TextureBinding* layer_height = find_layer_aux_binding(bindings, "height", layer.layer_role, layer.layer_channel);
        if (mask != nullptr) {
            layer.mask_source = mask->source_path;
            layer.mask_archive_path = mask->archive_path;
            layer.mask_parameter = mask->parameter_name;
        } else {
            layer.evidence_grade = "approximate";
        }
        if (layer_normal != nullptr) {
            layer.normal_source = layer_normal->source_path;
            layer.normal_archive_path = layer_normal->archive_path;
        }
        if (layer_material != nullptr) {
            layer.material_source = layer_material->source_path;
            layer.material_archive_path = layer_material->archive_path;
            layer.roughness_hint = std::max(layer.roughness_hint, layer_material->roughness_hint);
            layer.metalness_hint = std::max(layer.metalness_hint, layer_material->metalness_hint);
            layer.specular_hint = std::max(layer.specular_hint, layer_material->specular_hint);
        }
        if (layer_height != nullptr) {
            layer.height_source = layer_height->source_path;
            layer.height_archive_path = layer_height->archive_path;
            layer.height_scale_hint = std::max(layer.height_scale_hint, layer_height->height_scale_hint);
        }
        layers.push_back(layer);
        if (layers.size() >= 5) break;
    }
    return layers;
}

static std::string material_layer_json(const MaterialLayer& layer) {
    std::ostringstream out;
    out << "{"
        << "\"layer_role\":\"" << json_escape(layer.layer_role) << "\","
        << "\"mask_channel\":\"" << json_escape(layer.layer_channel) << "\","
        << "\"shader_family\":\"" << json_escape(layer.shader_family) << "\","
        << "\"shader_rule\":\"" << json_escape(layer.shader_rule) << "\","
        << "\"evidence_grade\":\"" << json_escape(layer.evidence_grade) << "\","
        << "\"blend_order\":\"" << json_escape(layer.blend_order) << "\","
        << "\"source_parameter\":\"" << json_escape(layer.source_parameter) << "\","
        << "\"mask_parameter\":\"" << json_escape(layer.mask_parameter) << "\","
        << "\"diffuse_source\":\"" << json_escape(layer.diffuse_source) << "\","
        << "\"diffuse_archive_path\":\"" << json_escape(layer.diffuse_archive_path) << "\","
        << "\"normal_source\":\"" << json_escape(layer.normal_source) << "\","
        << "\"normal_archive_path\":\"" << json_escape(layer.normal_archive_path) << "\","
        << "\"material_source\":\"" << json_escape(layer.material_source) << "\","
        << "\"material_archive_path\":\"" << json_escape(layer.material_archive_path) << "\","
        << "\"height_source\":\"" << json_escape(layer.height_source) << "\","
        << "\"height_archive_path\":\"" << json_escape(layer.height_archive_path) << "\","
        << "\"mask_source\":\"" << json_escape(layer.mask_source) << "\","
        << "\"mask_archive_path\":\"" << json_escape(layer.mask_archive_path) << "\","
        << "\"weight\":" << layer.weight << ","
        << "\"roughness_hint\":" << layer.roughness_hint << ","
        << "\"metalness_hint\":" << layer.metalness_hint << ","
        << "\"specular_hint\":" << layer.specular_hint << ","
        << "\"height_scale_hint\":" << layer.height_scale_hint << ","
        << "\"tint\":[" << layer.tint[0] << "," << layer.tint[1] << "," << layer.tint[2] << "," << layer.tint[3] << "]"
        << "}";
    return out.str();
}

static bool job_allows_texture_role(const EntryJob& job, const std::string& role) {
    if (!job.use_textures) return false;
    if (role == "base") return true;
    if (job.disable_all_support_maps) return false;
    if (role == "normal") return !job.disable_normal_map;
    if (role == "height") return !job.disable_height_map;
    if (
        role == "material"
        || role == "occlusion"
        || role == "roughness"
        || role == "metalness"
        || role == "specular"
        || role == "detail"
    ) {
        return !job.disable_material_map;
    }
    return true;
}

static std::string native_asset_family_summary(const std::vector<NativeAssetFamilyRow>& rows) {
    int materials = 0;
    int textures = 0;
    int physics = 0;
    int meshinfo = 0;
    int prefab = 0;
    int skeleton = 0;
    for (const NativeAssetFamilyRow& row : rows) {
        if (row.group == "Material") ++materials;
        else if (row.group == "Textures") ++textures;
        else if (row.group == "Physics / HKX") ++physics;
        else if (row.group == "MeshInfo") ++meshinfo;
        else if (row.group == "Prefab / Metadata") ++prefab;
        else if (row.group == "Skeleton / Rig") ++skeleton;
    }
    std::ostringstream out;
    out << "Model OK";
    if (materials) out << " | " << materials << " material";
    if (textures) out << " | " << textures << " textures";
    if (physics) out << " | HKX hint";
    if (meshinfo) out << " | meshinfo hint";
    if (prefab) out << " | prefab hint";
    if (skeleton) out << " | skeletons hint";
    return out.str();
}

static std::string native_asset_family_json(const NativePackage& package, const EntryJob& job) {
    std::ostringstream out;
    out << "\"asset_family\":{"
        << "\"source\":\"native-core\","
        << "\"schema_version\":" << kNativePackageSchemaVersion << ","
        << "\"root_path\":\"" << json_escape(job.path) << "\","
        << "\"family_key\":\"" << json_escape(stem_from_path(job.path)) << "\","
        << "\"summary\":\"" << json_escape(native_asset_family_summary(package.asset_family_rows)) << "\","
        << "\"reference_count\":" << package.asset_family_reference_count << ","
        << "\"member_rows\":[";
    for (size_t i = 0; i < package.asset_family_rows.size(); ++i) {
        const NativeAssetFamilyRow& row = package.asset_family_rows[i];
        if (i) out << ",";
        out << "{"
            << "\"group\":\"" << json_escape(row.group) << "\","
            << "\"role\":\"" << json_escape(row.role) << "\","
            << "\"display_name\":\"" << json_escape(row.display_name) << "\","
            << "\"path\":\"" << json_escape(row.path) << "\","
            << "\"status\":\"" << json_escape(row.status) << "\","
            << "\"evidence\":\"" << json_escape(row.evidence) << "\","
            << "\"confidence\":\"" << json_escape(row.confidence) << "\","
            << "\"include_policy\":\"" << json_escape(row.include_policy) << "\","
            << "\"reason\":\"" << json_escape(row.reason) << "\","
            << "\"relation_kind\":\"" << json_escape(row.relation_kind) << "\","
            << "\"semantic_label\":\"" << json_escape(row.semantic_label) << "\","
            << "\"semantic_hint\":\"" << json_escape(row.semantic_hint) << "\","
            << "\"sidecar_parameter_name\":\"" << json_escape(row.sidecar_parameter_name) << "\","
            << "\"material_name\":\"" << json_escape(row.material_name) << "\","
            << "\"package_label\":\"" << json_escape(row.package_label) << "\","
            << "\"sidecar_kind\":\"" << json_escape(row.sidecar_kind) << "\","
            << "\"shader_family\":\"" << json_escape(row.shader_family) << "\","
            << "\"texture_role\":\"" << json_escape(row.texture_role) << "\","
            << "\"source_table\":\"" << json_escape(row.source_table) << "\","
            << "\"source_field\":\"" << json_escape(row.source_field) << "\""
            << "}";
    }
    out << "],\"references\":[";
    bool first = true;
    for (const NativeAssetFamilyRow& row : package.asset_family_rows) {
        if (row.group == "Selected Model") continue;
        if (row.path.empty()) continue;
        if (!first) out << ",";
        first = false;
        out << "{"
            << "\"reference_name\":\"" << json_escape(row.display_name.empty() ? basename_from_path(row.path) : row.display_name) << "\","
            << "\"material_name\":\"" << json_escape(row.material_name) << "\","
            << "\"semantic_label\":\"" << json_escape(row.semantic_label) << "\","
            << "\"semantic_hint\":\"" << json_escape(row.semantic_hint) << "\","
            << "\"sidecar_parameter_name\":\"" << json_escape(row.sidecar_parameter_name) << "\","
            << "\"sidecar_kind\":\"" << json_escape(row.sidecar_kind) << "\","
            << "\"shader_family\":\"" << json_escape(row.shader_family) << "\","
            << "\"texture_role\":\"" << json_escape(row.texture_role) << "\","
            << "\"resolution_status\":\"" << json_escape(lower_copy(row.status) == "resolved" ? "resolved" : "missing") << "\","
            << "\"resolved_archive_path\":\"" << json_escape(row.path) << "\","
            << "\"resolved_package_label\":\"" << json_escape(row.package_label) << "\","
            << "\"reference_kind\":\"" << json_escape(row.relation_kind.empty() ? "metadata" : row.relation_kind) << "\","
            << "\"relation_group\":\"" << json_escape(row.group) << "\","
            << "\"relation_reason\":\"" << json_escape(row.reason) << "\","
            << "\"relation_confidence\":\"" << json_escape(row.confidence) << "\","
            << "\"source_table\":\"" << json_escape(row.source_table) << "\","
            << "\"source_field\":\"" << json_escape(row.source_field) << "\""
            << "}";
    }
    out << "]}";
    return out.str();
}

static NativePackage write_d3d11_package(
    const EntryJob& job,
    const std::vector<NativeSubmesh>& submeshes,
    const std::vector<TextureBinding>& bindings,
    NativePackage package
) {
    if (submeshes.empty()) throw std::runtime_error("native package writer received no submeshes");
    const fs::path package_dir = job.output_root;
    const fs::path geometry_dir = package_dir / "geometry";
    fs::create_directories(geometry_dir);
    Vec3 min_v{1.0e30f, 1.0e30f, 1.0e30f};
    Vec3 max_v{-1.0e30f, -1.0e30f, -1.0e30f};
    int source_vertex_total = 0;
    int face_total = 0;
    for (const NativeSubmesh& mesh : submeshes) {
        source_vertex_total += static_cast<int>(mesh.positions.size());
        face_total += static_cast<int>(mesh.indices.size() / 3u);
        for (const Vec3& p : mesh.positions) {
            min_v.x = std::min(min_v.x, p.x); min_v.y = std::min(min_v.y, p.y); min_v.z = std::min(min_v.z, p.z);
            max_v.x = std::max(max_v.x, p.x); max_v.y = std::max(max_v.y, p.y); max_v.z = std::max(max_v.z, p.z);
        }
    }
    const Vec3 center{(min_v.x + max_v.x) * 0.5f, (min_v.y + max_v.y) * 0.5f, (min_v.z + max_v.z) * 0.5f};
    const float max_dim = std::max({max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z, 1.0e-6f});
    const float scale = 2.0f / max_dim;

    std::ostringstream batches_json;
    std::ostringstream material_slots_json;
    std::ostringstream selection_decisions_json;
    int emitted_batch_count = 0;
    int emitted_vertex_count = 0;
    for (size_t batch_index = 0; batch_index < submeshes.size(); ++batch_index) {
        const NativeSubmesh& mesh = submeshes[batch_index];
        if (mesh.indices.size() < 3) continue;
        const std::string stem = batch_stem(batch_index);
        const fs::path geometry_path = geometry_dir / (stem + ".bin");
        const fs::path identity_path = geometry_dir / (stem + "_identity.bin");
        auto color = color_for_batch(static_cast<int>(batch_index));
        write_geometry_blob(geometry_path, identity_path, mesh, center, scale, color);
        const int vertex_count = static_cast<int>(mesh.indices.size());
        emitted_vertex_count += vertex_count;
        int base_score = 0;
        int normal_score = 0;
        int material_score = 0;
        int height_score = 0;
        int specular_score = 0;
        int detail_score = 0;
        const TextureBinding* base = job_allows_texture_role(job, "base") ? best_base_binding_for_mode(bindings, mesh, job, &base_score) : nullptr;
        const TextureBinding* normal = job_allows_texture_role(job, "normal") ? best_binding_for_role(bindings, mesh, "normal", &normal_score, &package.rejected_texture_examples) : nullptr;
        const TextureBinding* material = job_allows_texture_role(job, "material") ? best_binding_for_role(bindings, mesh, "material", &material_score, &package.rejected_texture_examples) : nullptr;
        const TextureBinding* height = job_allows_texture_role(job, "height") ? best_binding_for_role(bindings, mesh, "height", &height_score, &package.rejected_texture_examples) : nullptr;
        const TextureBinding* specular = job_allows_texture_role(job, "specular") ? best_binding_for_role(bindings, mesh, "specular", &specular_score, &package.rejected_texture_examples) : nullptr;
        const TextureBinding* detail = job_allows_texture_role(job, "detail") ? best_binding_for_role(bindings, mesh, "detail", &detail_score, &package.rejected_texture_examples) : nullptr;
        const int base_identity_score = base == nullptr ? 0 : material_identity_match_score(*base, mesh);
        const int base_largest_dimension = base == nullptr ? 0 : std::max(base->dds_width, base->dds_height);
        const bool base_technical = base != nullptr && technical_for_visible_base(base->parameter_name, base->archive_path, base->role);
        const bool base_low_authority = base != nullptr && (low_authority_base_path(base->archive_path) || low_authority_base_path(base->texture_name));
        const bool base_low_res = base != nullptr && base_largest_dimension > 0 && base_largest_dimension < 512 && !base_low_authority;
        const bool base_low_confidence = base != nullptr && base_score < 120 && base_identity_score < 72;
        if (job.use_textures && base == nullptr) {
            ++package.base_missing_count;
            package.material_quality_safe = false;
            package.base_quality_notes.push_back("batch " + std::to_string(batch_index) + " " + mesh.material + ": no reliable base DDS");
        } else if (job.use_textures && base_technical) {
            ++package.base_technical_count;
            package.material_quality_safe = false;
            package.base_quality_notes.push_back("batch " + std::to_string(batch_index) + " " + mesh.material + ": technical base rejected " + base->texture_name);
        } else if (job.use_textures && base_low_res) {
            ++package.base_low_res_count;
            package.material_quality_safe = false;
            package.base_quality_notes.push_back("batch " + std::to_string(batch_index) + " " + mesh.material + ": low-resolution base " + base->texture_name + " " + std::to_string(base->dds_width) + "x" + std::to_string(base->dds_height));
        } else if (job.use_textures && base_low_authority) {
            package.base_quality_notes.push_back("batch " + std::to_string(batch_index) + " " + mesh.material + ": low-authority base fallback " + base->texture_name);
        } else if (job.use_textures && base_low_confidence) {
            ++package.base_low_confidence_count;
            package.material_quality_safe = false;
            package.base_quality_notes.push_back("batch " + std::to_string(batch_index) + " " + mesh.material + ": low-confidence base " + base->texture_name + " score=" + std::to_string(base_score) + " identity=" + std::to_string(base_identity_score));
        }
        const std::vector<const TextureBinding*> batch_bindings = relevant_bindings_for_mesh(
            bindings,
            mesh,
            {base, normal, material, height, specular, detail}
        );
        const NativeMaterialHints material_hints = material_hints_for_bindings(batch_bindings);
        if (base == nullptr) {
            for (const TextureBinding* binding_ptr : batch_bindings) {
                if (binding_ptr == nullptr) continue;
                const auto tint = binding_ptr->tint_color;
                const bool has_tint = std::abs(tint[0] - 1.0f) > 0.02f || std::abs(tint[1] - 1.0f) > 0.02f || std::abs(tint[2] - 1.0f) > 0.02f;
                if (has_tint) {
                    color = {std::clamp(tint[0], 0.05f, 1.0f), std::clamp(tint[1], 0.05f, 1.0f), std::clamp(tint[2], 0.05f, 1.0f)};
                    package.base_quality_notes.push_back("batch " + std::to_string(batch_index) + " " + mesh.material + ": native material tint fallback used because no true base DDS was selected");
                    break;
                }
            }
        }
        const bool held_layer_albedo = shader_rule_holds_layer_albedo(batch_bindings);
        const std::vector<MaterialLayer> material_layers = compile_material_layers(
            batch_bindings,
            base,
            normal,
            material,
            height,
            specular,
            material_hints
        );
        const MaterialLayer* primary_layer = nullptr;
        for (const MaterialLayer& layer : material_layers) {
            if (layer.layer_role != "base" && !layer.diffuse_source.empty()) {
                primary_layer = &layer;
                break;
            }
        }
        if (package.selected_texture_examples.size() < 12) {
            auto texture_label = [](const TextureBinding* binding) -> std::string {
                if (binding == nullptr) return "-";
                std::string text = binding->texture_name.empty() ? basename_from_path(binding->archive_path) : binding->texture_name;
                const int largest_dimension = std::max(binding->dds_width, binding->dds_height);
                if (largest_dimension > 0) {
                    text += " " + std::to_string(binding->dds_width) + "x" + std::to_string(binding->dds_height);
                }
                if (!binding->dds_format.empty()) {
                    text += " " + binding->dds_format;
                }
                return text;
            };
            package.selected_texture_examples.push_back(
                "batch " + std::to_string(batch_index) + " " + mesh.material
                + ": base=" + texture_label(base)
                + ", normal=" + texture_label(normal)
                + ", material=" + texture_label(material)
                + ", height=" + texture_label(height)
                + ", uv_flip_policy=legacy_no_flip"
                + ", normal_y_policy=shader_invert_legacy_compat"
            );
        }
        if (emitted_batch_count > 0) {
            material_slots_json << ",";
            selection_decisions_json << ",";
        }
        material_slots_json << "{"
            << "\"batch_index\":" << batch_index << ","
            << "\"material_name\":\"" << json_escape(mesh.material) << "\","
            << "\"submesh_name\":\"" << json_escape(mesh.name) << "\","
            << "\"shader_family\":\"" << json_escape(batch_bindings.empty() ? "" : batch_bindings.front()->shader_family) << "\","
            << "\"shader_rule\":\"" << json_escape(batch_bindings.empty() ? "generic" : batch_bindings.front()->shader_rule) << "\","
            << "\"base\":\"" << json_escape(base == nullptr ? "" : base->archive_path) << "\","
            << "\"normal\":\"" << json_escape(normal == nullptr ? "" : normal->archive_path) << "\","
            << "\"material\":\"" << json_escape(material == nullptr ? "" : material->archive_path) << "\","
            << "\"specular\":\"" << json_escape(specular == nullptr ? "" : specular->archive_path) << "\","
            << "\"height\":\"" << json_escape(height == nullptr ? "" : height->archive_path) << "\","
            << "\"detail\":\"" << json_escape(detail == nullptr ? "" : detail->archive_path) << "\""
            << "}";
        selection_decisions_json << "{"
            << "\"batch_index\":" << batch_index << ","
            << "\"visible_texture_mode\":\"" << json_escape(job.visible_texture_mode) << "\","
            << "\"base_selected\":\"" << json_escape(base == nullptr ? "" : base->archive_path) << "\","
            << "\"base_score\":" << base_score << ","
            << "\"base_identity_score\":" << base_identity_score << ","
            << "\"base_missing\":" << (base == nullptr ? "true" : "false") << ","
            << "\"base_technical\":" << (base_technical ? "true" : "false") << ","
            << "\"base_low_res\":" << (base_low_res ? "true" : "false") << ","
            << "\"base_low_confidence\":" << (base_low_confidence ? "true" : "false") << ","
            << "\"uv_flip_policy\":\"legacy_no_flip\","
            << "\"normal_y_policy\":\"shader_invert_legacy_compat\","
            << "\"evidence_grade\":\"" << json_escape(material_layers.empty() ? "approximate" : material_layers.front().evidence_grade) << "\""
            << "}";
        if (emitted_batch_count++) batches_json << ",";
        batches_json << "{"
            << "\"index\":" << batch_index << ","
            << "\"material_name\":\"" << json_escape(mesh.material) << "\","
            << "\"texture_name\":\"" << json_escape(mesh.material.empty() ? mesh.name : mesh.material) << "\","
            << "\"vertex_file\":\"" << json_escape(geometry_path.lexically_relative(package_dir).generic_string()) << "\","
            << "\"vertex_count\":" << vertex_count << ","
            << "\"editor_identity\":{\"source_submesh_index\":" << mesh.source_submesh_index
            << ",\"identity_file\":\"" << json_escape(identity_path.lexically_relative(package_dir).generic_string()) << "\"},"
            << "\"base_color\":[" << color[0] << "," << color[1] << "," << color[2] << "],"
            << "\"textures\":{},"
            << "\"dds_textures\":{";
        bool wrote_slot = false;
        for (const auto& slot_pair : std::vector<std::pair<std::string, const TextureBinding*>>{
            {"base", base},
            {"normal", normal},
            {"material", material},
            {"height", height},
        }) {
            if (!job_allows_texture_role(job, slot_pair.first)) continue;
            const std::string slot_json = dds_entry_json(slot_pair.second, slot_pair.first);
            if (slot_json.empty()) continue;
            if (wrote_slot) batches_json << ",";
            batches_json << slot_json;
            wrote_slot = true;
        }
        if (!batch_bindings.empty()) {
            if (wrote_slot) batches_json << ",";
            batches_json << "\"material_inputs\":[";
            bool first_input = true;
            for (const TextureBinding* binding_ptr : batch_bindings) {
                if (binding_ptr == nullptr || binding_ptr->source_path.empty()) continue;
                const TextureBinding& binding = *binding_ptr;
                if (!job_allows_texture_role(job, binding.role)) continue;
                if (!first_input) batches_json << ",";
                first_input = false;
                batches_json << "{"
                    << "\"slot\":\"" << json_escape(binding.role) << "\","
                    << "\"source_path\":\"" << json_escape(binding.source_path) << "\","
                    << "\"archive_path\":\"" << json_escape(binding.archive_path) << "\","
                    << "\"parameter_name\":\"" << json_escape(binding.parameter_name) << "\","
                    << "\"semantic_type\":\"" << json_escape(binding.semantic_type) << "\","
                    << "\"semantic_subtype\":\"" << json_escape(binding.semantic_subtype) << "\","
                    << "\"material_name\":\"" << json_escape(binding.material_name) << "\","
                    << "\"shader_family\":\"" << json_escape(binding.shader_family) << "\","
                    << "\"shader_rule\":\"" << json_escape(binding.shader_rule) << "\","
                    << "\"sidecar_path\":\"" << json_escape(binding.sidecar_path) << "\","
                    << "\"sidecar_kind\":\"" << json_escape(binding.sidecar_kind) << "\","
                    << "\"linked_mesh_path\":\"" << json_escape(binding.linked_mesh_path) << "\","
                    << "\"packed_channels\":\"" << json_escape(binding.packed_channels) << "\","
                    << "\"srgb_mode\":\"" << json_escape(binding.srgb_mode) << "\","
                    << "\"parameter_declared_by\":\"" << json_escape(binding.parameter_declared_by) << "\","
                    << "\"material_output_quality\":\"" << json_escape(binding.material_output_quality) << "\","
                    << "\"evidence_grade\":\"" << json_escape(binding.evidence_grade) << "\","
                    << "\"layer_role\":\"" << json_escape(binding.layer_role) << "\","
                    << "\"layer_channel\":\"" << json_escape(binding.layer_channel) << "\","
                    << "\"layer_weight\":" << binding.layer_weight << ","
                    << "\"blend_flags\":\"" << json_escape(binding.blend_flags) << "\","
                    << "\"material_parameter_names\":\"" << json_escape(binding.material_parameter_names) << "\","
                    << "\"visible_class\":\"" << json_escape(binding.visible_class) << "\","
                    << "\"source_authority\":\"" << json_escape(binding.source_authority) << "\","
                    << "\"relation_confidence\":\"" << json_escape(binding.relation_confidence) << "\","
                    << "\"relation_reason\":\"" << json_escape(binding.relation_reason) << "\","
                    << "\"width\":" << binding.dds_width << ","
                    << "\"height\":" << binding.dds_height << ","
                    << "\"format\":\"" << json_escape(binding.dds_format) << "\","
                    << "\"available\":true,"
                    << "\"direct_upload_candidate\":true"
                    << "}";
            }
            batches_json << "]";
        }
        batches_json << "},"
            << "\"texture_flip_vertical\":false,"
            << "\"uv_flip_policy\":\"legacy_no_flip\","
            << "\"normal_y_policy\":\"shader_invert_legacy_compat\","
            << "\"selected_texture_slots\":{"
            << "\"base\":{\"match_score\":" << base_score << ",\"identity_score\":" << base_identity_score << ",\"archive_path\":\"" << json_escape(base == nullptr ? "" : base->archive_path) << "\"},"
            << "\"normal\":{\"match_score\":" << normal_score << ",\"identity_score\":" << (normal == nullptr ? 0 : material_identity_match_score(*normal, mesh)) << ",\"archive_path\":\"" << json_escape(normal == nullptr ? "" : normal->archive_path) << "\"},"
            << "\"material\":{\"match_score\":" << material_score << ",\"identity_score\":" << (material == nullptr ? 0 : material_identity_match_score(*material, mesh)) << ",\"archive_path\":\"" << json_escape(material == nullptr ? "" : material->archive_path) << "\"},"
            << "\"specular\":{\"match_score\":" << specular_score << ",\"identity_score\":" << (specular == nullptr ? 0 : material_identity_match_score(*specular, mesh)) << ",\"archive_path\":\"" << json_escape(specular == nullptr ? "" : specular->archive_path) << "\"},"
            << "\"height\":{\"match_score\":" << height_score << ",\"identity_score\":" << (height == nullptr ? 0 : material_identity_match_score(*height, mesh)) << ",\"archive_path\":\"" << json_escape(height == nullptr ? "" : height->archive_path) << "\"},"
            << "\"detail\":{\"match_score\":" << detail_score << ",\"identity_score\":" << (detail == nullptr ? 0 : material_identity_match_score(*detail, mesh)) << ",\"archive_path\":\"" << json_escape(detail == nullptr ? "" : detail->archive_path) << "\"}"
            << "},"
            << "\"has_texture_coordinates\":true,"
            << "\"tangents_usable\":true,"
            << "\"shader_family\":\"" << json_escape(batch_bindings.empty() ? "" : batch_bindings.front()->shader_family) << "\","
            << "\"shader_rule\":\"" << json_escape(batch_bindings.empty() ? "generic" : batch_bindings.front()->shader_rule) << "\","
            << "\"evidence_grade\":\"" << json_escape(material_layers.empty() ? "approximate" : material_layers.front().evidence_grade) << "\","
            << "\"material_layer_count\":" << (material_layers.size() > 0 ? std::max<int>(0, static_cast<int>(material_layers.size()) - 1) : 0) << ","
            << "\"material_layers\":[";
        for (size_t layer_index = 0; layer_index < material_layers.size(); ++layer_index) {
            if (layer_index) batches_json << ",";
            batches_json << material_layer_json(material_layers[layer_index]);
        }
        batches_json << "],"
            << "\"primary_material_layer\":{"
            << "\"active\":" << (primary_layer != nullptr ? "true" : "false") << ","
            << "\"layer_role\":\"" << json_escape(primary_layer == nullptr ? "" : primary_layer->layer_role) << "\","
            << "\"mask_channel\":\"" << json_escape(primary_layer == nullptr ? "r" : primary_layer->layer_channel) << "\","
            << "\"weight\":" << (primary_layer == nullptr ? 0.0f : primary_layer->weight) << ","
            << "\"diffuse_source\":\"" << json_escape(primary_layer == nullptr ? "" : primary_layer->diffuse_source) << "\","
            << "\"mask_source\":\"" << json_escape(primary_layer == nullptr ? "" : primary_layer->mask_source) << "\","
            << "\"material_source\":\"" << json_escape(primary_layer == nullptr ? "" : primary_layer->material_source) << "\","
            << "\"normal_source\":\"" << json_escape(primary_layer == nullptr ? "" : primary_layer->normal_source) << "\","
            << "\"height_source\":\"" << json_escape(primary_layer == nullptr ? "" : primary_layer->height_source) << "\","
            << "\"tint\":[" << (primary_layer == nullptr ? 1.0f : primary_layer->tint[0]) << "," << (primary_layer == nullptr ? 1.0f : primary_layer->tint[1]) << "," << (primary_layer == nullptr ? 1.0f : primary_layer->tint[2]) << "," << (primary_layer == nullptr ? 1.0f : primary_layer->tint[3]) << "],"
            << "\"roughness_hint\":" << (primary_layer == nullptr ? 0.0f : primary_layer->roughness_hint) << ","
            << "\"metalness_hint\":" << (primary_layer == nullptr ? 0.0f : primary_layer->metalness_hint) << ","
            << "\"specular_hint\":" << (primary_layer == nullptr ? 0.0f : primary_layer->specular_hint) << ","
            << "\"height_scale_hint\":" << (primary_layer == nullptr ? 0.0f : primary_layer->height_scale_hint)
            << "},"
            << "\"unknown_parameters\":[";
        bool first_unknown = true;
        std::set<std::string> unknown_parameter_names;
        for (const TextureBinding* binding_ptr : batch_bindings) {
            if (binding_ptr == nullptr) continue;
            if (binding_ptr->role == "base" || binding_ptr->role == "normal" || binding_ptr->role == "height" || binding_ptr->role == "material" || binding_ptr->role == "specular" || binding_ptr->role == "detail") continue;
            if (!binding_ptr->parameter_name.empty()) unknown_parameter_names.insert(binding_ptr->parameter_name);
        }
        for (const std::string& name : unknown_parameter_names) {
            if (!first_unknown) batches_json << ",";
            first_unknown = false;
            batches_json << "\"" << json_escape(name) << "\"";
        }
        batches_json << "],"
            << "\"rejected_inputs\":[";
        bool first_rejected = true;
        for (const TextureBinding* binding_ptr : batch_bindings) {
            if (binding_ptr == nullptr) continue;
            if (binding_ptr->role == "base" && technical_for_visible_base(binding_ptr->parameter_name, binding_ptr->archive_path, binding_ptr->role)) {
                if (!first_rejected) batches_json << ",";
                first_rejected = false;
                batches_json << "{\"parameter_name\":\"" << json_escape(binding_ptr->parameter_name) << "\",\"archive_path\":\"" << json_escape(binding_ptr->archive_path) << "\",\"reason\":\"technical map rejected as albedo\"}";
            }
        }
        batches_json << "],"
            << "\"native_base_quality\":{\"safe\":" << ((!job.use_textures || (base != nullptr && !base_technical && !base_low_res && !base_low_confidence)) ? "true" : "false")
            << ",\"score\":" << base_score
            << ",\"identity_score\":" << base_identity_score
            << ",\"low_res\":" << (base_low_res ? "true" : "false")
            << ",\"low_authority\":" << (base_low_authority ? "true" : "false")
            << ",\"technical\":" << (base_technical ? "true" : "false")
            << ",\"missing\":" << (base == nullptr ? "true" : "false")
            << ",\"visible_class\":\"" << json_escape(base == nullptr ? "" : base->visible_class) << "\""
            << ",\"source_authority\":\"" << json_escape(base == nullptr ? "" : base->source_authority) << "\""
            << ",\"source\":\"" << json_escape(base == nullptr ? "" : base->source_path) << "\""
            << ",\"archive_path\":\"" << json_escape(base == nullptr ? "" : base->archive_path) << "\""
            << ",\"texture_name\":\"" << json_escape(base == nullptr ? "" : base->texture_name) << "\""
            << ",\"width\":" << (base == nullptr ? 0 : base->dds_width)
            << ",\"height\":" << (base == nullptr ? 0 : base->dds_height)
            << ",\"format\":\"" << json_escape(base == nullptr ? "" : base->dds_format) << "\"},"
            << "\"normal_strength\":" << job.normal_strength_cap << ","
            << "\"height_amount\":" << std::clamp(job.height_effect_max * 0.12f, 0.0f, 0.16f) << ","
            << "\"roughness\":" << material_hints.roughness << ","
            << "\"metalness\":" << material_hints.metalness << ","
            << "\"specular\":" << material_hints.specular << ","
            << "\"height_scale\":" << material_hints.height_scale << ","
            << "\"native_material_hints\":{\"shader_family\":\"" << json_escape(batch_bindings.empty() ? "" : batch_bindings.front()->shader_family) << "\",\"roughness\":" << material_hints.roughness << ",\"metalness\":" << material_hints.metalness << ",\"specular\":" << material_hints.specular << ",\"height_scale\":" << material_hints.height_scale << "},"
            << "\"notes\":[\"generated by cdmw-preview-core " << json_escape(package.mesh_parse) << " path\",\"native material inputs scoped to this batch: " << batch_bindings.size() << "\""
            << (held_layer_albedo ? ",\"skin/hair visible layer albedo held until mask semantics are validated\"" : "")
            << "],"
            << "\"material_combiner_active\":false,"
            << "\"material_combiner_outputs\":[],"
            << "\"material_combiner_decode_modes\":[\"direct_dds_sidecar\"]"
            << "}";
    }
    package.path = package_dir;
    package.batch_count = emitted_batch_count;
    package.vertex_count = emitted_vertex_count;
    package.face_count = face_total;
    add_asset_family_row(package, NativeAssetFamilyRow{
        "Selected Model",
        "Model",
        job.entry.basename.empty() ? basename_from_path(job.path) : job.entry.basename,
        job.path,
        "Model OK",
        "Selected",
        "exact_path",
        "required",
        "The file currently selected in Archive Browser.",
        "model",
        "Selected model",
        "",
        "",
        "",
        package_label_for_ref(job.entry),
        "",
        "",
        "",
        "",
        ""
    });
    const PamtIndex& package_index_for_family = cached_pamt_index(job.entry.pamt_path);
    const std::string model_stem = stem_from_path(job.path);
    const std::vector<std::pair<std::string, std::pair<std::string, std::string>>> related_exact_basenames = {
        {model_stem + ".meshinfo", {"MeshInfo", "Meshinfo"}},
        {model_stem + ".hkx", {"Physics / HKX", "HKX / Physics"}},
        {model_stem + ".prefab", {"Prefab / Metadata", "Prefab"}},
        {model_stem + ".prefabdata_xml", {"Prefab / Metadata", "Prefab Data"}},
        {model_stem + ".pab", {"Skeleton / Rig", "Skeleton"}},
    };
    for (const auto& related : related_exact_basenames) {
        for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(job, package_index_for_family, related.first, 8)) {
            add_asset_family_row(package, NativeAssetFamilyRow{
                related.second.first,
                related.second.second,
                ref.basename.empty() ? basename_from_path(ref.path) : ref.basename,
                ref.path,
                "Resolved",
                "Same stem",
                "derived_same_stem",
                "manual",
                "Native preview-core found a same-stem related archive entry.",
                "metadata",
                related.second.second,
                "",
                "",
                "",
                package_label_for_ref(ref),
                ref.extension,
                "",
                "",
                "",
                ""
            });
        }
    }
    for (const ArchiveEntryRef& ref : lookup_basename_candidates_across_package(job, package_index_for_family, "identityskeleton.pab", 4)) {
        add_asset_family_row(package, NativeAssetFamilyRow{
            "Skeleton / Rig",
            "Skeleton",
            ref.basename.empty() ? basename_from_path(ref.path) : ref.basename,
            ref.path,
            "Resolved",
            "Name hint",
            "derived_family_heuristic",
            "manual",
            "Native preview-core found the common identity skeleton companion.",
            "skeleton",
            "Skeleton",
            "",
            "",
            "",
            package_label_for_ref(ref),
            ref.extension,
            "",
            "",
            "",
            ""
        });
    }
    package.asset_family_reference_count = std::max(0, static_cast<int>(package.asset_family_rows.size()) - 1);
    const std::string format = job.extension.size() > 1 && job.extension.front() == '.'
        ? job.extension.substr(1)
        : job.extension;
    std::ostringstream manifest;
    manifest << "{"
        << "\"schema_version\":" << std::max(kNativePackageSchemaVersion, job.schema_version) << ","
        << "\"material_semantics_version\":" << kNativeMaterialSemanticsVersion << ","
        << "\"material_graph_version\":" << kNativeMaterialGraphVersion << ","
        << "\"backend\":\"d3d11\","
        << "\"source_path\":\"" << json_escape(job.path) << "\","
        << "\"format\":\"" << json_escape(format) << "\","
        << "\"summary\":\"Native preview-core " << json_escape(format) << " package\","
        << "\"visible_texture_mode\":\"" << json_escape(job.visible_texture_mode) << "\","
        << "\"mesh_count\":" << emitted_batch_count << ","
        << "\"source_vertex_count\":" << source_vertex_total << ","
        << "\"vertex_count\":" << emitted_vertex_count << ","
        << "\"face_count\":" << face_total << ","
        << "\"normalization_center\":[" << center.x << "," << center.y << "," << center.z << "],"
        << "\"normalization_scale\":" << scale << ","
        << "\"orbit_sensitivity\":" << job.orbit_sensitivity << ","
        << "\"pan_sensitivity\":" << job.pan_sensitivity << ","
        << "\"invert_orbit_x\":" << (job.invert_orbit_x ? "true" : "false") << ","
        << "\"invert_orbit_y\":" << (job.invert_orbit_y ? "true" : "false") << ","
        << "\"invert_pan_x\":" << (job.invert_pan_x ? "true" : "false") << ","
        << "\"invert_pan_y\":" << (job.invert_pan_y ? "true" : "false") << ","
        << "\"max_anisotropy\":" << job.max_anisotropy << ","
        << "\"ambient_strength\":" << job.ambient_strength << ","
        << "\"diffuse_light_scale\":" << job.diffuse_light_scale << ","
        << "\"specular_base\":" << job.specular_base << ","
        << "\"specular_max\":" << job.specular_max << ","
        << "\"shininess_min\":" << job.shininess_min << ","
        << "\"shininess_max\":" << job.shininess_max << ","
        << "\"use_textures\":" << (job.use_textures ? "true" : "false") << ","
        << "\"high_quality_textures\":" << (job.high_quality_textures ? "true" : "false") << ","
        << "\"native_preview_core\":{\"mesh_parse\":\"" << json_escape(package.mesh_parse) << "\",\"material_index\":\"" << json_escape(package.material_index) << "\",\"material_graph_status\":\"" << json_escape(package.material_graph_status) << "\",\"material_graph_version\":" << kNativeMaterialGraphVersion << ",\"material_graph_cache_hit\":" << (package.material_graph_cache_hit ? "true" : "false") << ",\"material_graph_cache_path\":\"" << json_escape(package.material_graph_cache_path) << "\",\"texture_resolution\":\"" << json_escape(package.texture_resolution) << "\",\"material_output_quality\":\"" << json_escape(package.material_output_quality) << "\",\"material_semantics_version\":" << kNativeMaterialSemanticsVersion << ",\"material_quality_safe\":" << (package.material_quality_safe ? "true" : "false") << ",\"base_missing_count\":" << package.base_missing_count << ",\"base_low_res_count\":" << package.base_low_res_count << ",\"base_low_confidence_count\":" << package.base_low_confidence_count << ",\"base_technical_count\":" << package.base_technical_count << ",\"asset_family_reference_count\":" << package.asset_family_reference_count << ",\"visible_texture_mode\":\"" << json_escape(job.visible_texture_mode) << "\",\"lod_count\":" << package.lod_count << "},"
        << native_asset_family_json(package, job) << ","
        << "\"material_slots\":[" << material_slots_json.str() << "],"
        << "\"selection_decisions\":[" << selection_decisions_json.str() << "],"
        << "\"rejected_candidates\":[";
    for (size_t rejected_index = 0; rejected_index < package.rejected_texture_examples.size(); ++rejected_index) {
        if (rejected_index) manifest << ",";
        manifest << "\"" << json_escape(package.rejected_texture_examples[rejected_index]) << "\"";
    }
    manifest << "],"
        << "\"dds_upload_policy\":{\"default\":\"direct_dds\",\"png_fallback\":\"generated_or_non_dds_only\",\"base_srgb\":\"from_technique_or_role\",\"data_maps\":\"linear\",\"normal_y_policy\":\"per_batch\"},"
        << "\"batches\":[" << batches_json.str() << "]"
        << "}";
    write_text(package_dir / "manifest.json", manifest.str());
    return package;
}

static NativePackage try_generate_native_package(const EntryJob& job, const std::vector<char>& data) {
    NativePackage package;
    NativeMeshParseResult parsed;
    if (job.extension == ".pac") {
        parsed.meshes = parse_pac_submeshes(data);
        parsed.parser = "native_pac_par_sections";
    } else if (job.extension == ".pam") {
        parsed = parse_pam_submeshes(data);
    } else if (job.extension == ".pamlod") {
        parsed = parse_pamlod_submeshes(data);
    } else {
        throw std::runtime_error("native preview-core package generation only supports .pac, .pam, and .pamlod");
    }
    if (parsed.meshes.empty()) {
        throw std::runtime_error("native model parser found no renderable geometry");
    }
    package.mesh_parse = parsed.parser;
    package.lod_count = parsed.lod_count;
    const PamtIndex& index = cached_pamt_index(job.entry.pamt_path);
    std::vector<TextureBinding> bindings = build_material_bindings(job, index, parsed.meshes, package);
    append_mesh_reference_bindings(job, index, parsed.meshes, bindings, package);
    if (bindings.empty()) {
        if (package.material_index.empty()) package.material_index = "none";
        package.texture_resolution = "none";
        package.notes.push_back("native package emitted geometry with fallback batch colors because no direct DDS bindings were resolved");
    }
    return write_d3d11_package(job, parsed.meshes, bindings, package);
}

std::string preview_report_for_job(const fs::path& job_path) {
    const auto started = std::chrono::steady_clock::now();
    EntryJob job = parse_job(job_path);
    std::string status = "unsupported";
    std::string fallback_reason;
    std::string message;
    std::string format_fourcc;
    std::uint64_t bytes_read = 0;
    const int compression_type = static_cast<int>(job.flags & 0x0F);
    bool raw_read_ok = false;
    NativePackage package;
    const std::uint64_t cache_hits_before = decoded_entry_cache_hits();
    const std::uint64_t cache_misses_before = decoded_entry_cache_misses();
    const std::uint64_t cache_evictions_before = decoded_entry_cache_evictions();
    const std::uint64_t sidecar_cache_hits_before = sidecar_parse_cache_hits();
    const std::uint64_t sidecar_cache_misses_before = sidecar_parse_cache_misses();
    try {
        fs::create_directories(job.output_root);
        fs::create_directories(job.cache_root);
        auto data = read_entry_decoded_bytes(job);
        bytes_read = static_cast<std::uint64_t>(data.size());
        format_fourcc = fourcc_from_bytes(data);
        raw_read_ok = true;
        if (job.extension != ".pam" && job.extension != ".pamlod" && job.extension != ".pac") {
            fallback_reason = "selected entry is not a native-preview-core model target";
        } else if (compression_type != 0 && compression_type != 1 && compression_type != 2 && job.comp_size != job.orig_size) {
            fallback_reason = "native decompression/reconstruction is not enabled for this milestone";
        } else {
            try {
                package = try_generate_native_package(job, data);
                if (package.batch_count > 0 && !package.path.empty()) {
                    status = "ok";
                    fallback_reason.clear();
                    message = "native preview-core generated a D3D11 package";
                } else {
                    fallback_reason = "native preview-core generated no renderable batches";
                }
            } catch (const std::exception& native_exc) {
                fallback_reason = native_exc.what();
            }
        }
        if (message.empty()) {
            message = status == "ok"
                ? "native preview-core generated a D3D11 package"
                : "native preview-core did not generate a D3D11 package";
        }
    } catch (const std::exception& exc) {
        status = "error";
        fallback_reason = exc.what();
        message = "native archive IO preflight failed";
    }
    const double elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    const cdmw_native_diag::ProcessMemorySnapshot memory = cdmw_native_diag::current_process_memory();
    const std::string recycle_reason = service_recycle_reason(memory);
    std::ostringstream out;
    out << "{"
        << "\"status\":\"" << json_escape(status) << "\","
        << "\"backend\":\"cdmw_preview_core_0.1\","
        << "\"native_archive_io\":\"" << (raw_read_ok ? "ok" : "failed") << "\","
        << "\"native_mesh_parser\":\"" << json_escape(package.mesh_parse.empty() ? "pending" : package.mesh_parse) << "\","
        << "\"native_material_index\":\"" << json_escape(package.material_index.empty() ? "pending" : package.material_index) << "\","
        << "\"native_material_graph_status\":\"" << json_escape(package.material_graph_status) << "\","
        << "\"native_material_graph_cache_hit\":" << (package.material_graph_cache_hit ? "true" : "false") << ","
        << "\"native_material_graph_cache_path\":\"" << json_escape(package.material_graph_cache_path) << "\","
        << "\"native_texture_resolution\":\"" << json_escape(package.texture_resolution.empty() ? "pending" : package.texture_resolution) << "\","
        << "\"native_material_output_quality\":\"" << json_escape(package.material_output_quality.empty() ? "pending" : package.material_output_quality) << "\","
        << "\"material_quality_safe\":" << (package.material_quality_safe ? "true" : "false") << ","
        << "\"base_missing_count\":" << package.base_missing_count << ","
        << "\"base_low_res_count\":" << package.base_low_res_count << ","
        << "\"base_low_confidence_count\":" << package.base_low_confidence_count << ","
        << "\"base_technical_count\":" << package.base_technical_count << ","
        << "\"schema_version\":" << std::max(kNativePackageSchemaVersion, job.schema_version) << ","
        << "\"material_semantics_version\":" << kNativeMaterialSemanticsVersion << ","
        << "\"material_graph_version\":" << kNativeMaterialGraphVersion << ","
        << "\"visible_texture_mode\":\"" << json_escape(job.visible_texture_mode) << "\","
        << "\"entry_path\":\"" << json_escape(job.path) << "\","
        << "\"extension\":\"" << json_escape(job.extension) << "\","
        << "\"format_fourcc\":\"" << json_escape(format_fourcc) << "\","
        << "\"compression_type\":" << compression_type << ","
        << "\"bytes_read\":" << bytes_read << ","
        << "\"batch_count\":" << package.batch_count << ","
        << "\"vertex_count\":" << package.vertex_count << ","
        << "\"face_count\":" << package.face_count << ","
        << "\"lod_count\":" << package.lod_count << ","
        << "\"dds_candidates\":" << package.dds_candidates << ","
        << "\"dds_extracted\":" << package.dds_extracted << ","
        << "\"asset_family_reference_count\":" << package.asset_family_reference_count << ","
        << "\"decoded_cache_entries\":" << decoded_entry_cache_entries() << ","
        << "\"decoded_cache_bytes\":" << decoded_entry_cache_bytes() << ","
        << "\"decoded_cache_hits\":" << decoded_entry_cache_hits() << ","
        << "\"decoded_cache_misses\":" << decoded_entry_cache_misses() << ","
        << "\"decoded_cache_evictions\":" << decoded_entry_cache_evictions() << ","
        << "\"decoded_cache_job_hits\":" << (decoded_entry_cache_hits() - cache_hits_before) << ","
        << "\"decoded_cache_job_misses\":" << (decoded_entry_cache_misses() - cache_misses_before) << ","
        << "\"decoded_cache_job_evictions\":" << (decoded_entry_cache_evictions() - cache_evictions_before) << ","
        << "\"sidecar_parse_cache_hits\":" << sidecar_parse_cache_hits() << ","
        << "\"sidecar_parse_cache_misses\":" << sidecar_parse_cache_misses() << ","
        << "\"sidecar_parse_cache_job_hits\":" << (sidecar_parse_cache_hits() - sidecar_cache_hits_before) << ","
        << "\"sidecar_parse_cache_job_misses\":" << (sidecar_parse_cache_misses() - sidecar_cache_misses_before) << ","
        << "\"process_working_set_bytes\":" << (memory.ok ? memory.working_set_bytes : 0ull) << ","
        << "\"process_private_bytes\":" << (memory.ok ? memory.private_bytes : 0ull) << ","
        << "\"service_job_count\":" << g_service_job_count << ","
        << "\"service_recycle_reason\":\"" << json_escape(recycle_reason) << "\","
        << "\"elapsed_ms\":" << elapsed_ms << ","
        << "\"package_path\":\"" << json_escape(status == "ok" ? package.path.string() : "") << "\","
        << "\"fallback_reason\":\"" << json_escape(fallback_reason) << "\","
        << "\"message\":\"" << json_escape(message) << "\","
        << "\"base_quality_notes\":[";
    for (size_t i = 0; i < package.base_quality_notes.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.base_quality_notes[i]) << "\"";
    }
    out << "],"
        << "\"selected_texture_examples\":[";
    for (size_t i = 0; i < package.selected_texture_examples.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.selected_texture_examples[i]) << "\"";
    }
    out << "],"
        << "\"rejected_texture_examples\":[";
    for (size_t i = 0; i < package.rejected_texture_examples.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.rejected_texture_examples[i]) << "\"";
    }
    out << "],"
        << "\"notes\":[";
    for (size_t i = 0; i < package.notes.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(package.notes[i]) << "\"";
    }
    out << "]"
        << "}";
    return out.str();
}

struct CommonArgs {
    fs::path crash_dir;
    fs::path diagnostic_log;
};

CommonArgs parse_common_args(int argc, char** argv) {
    CommonArgs args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i] ? argv[i] : "";
        auto next = [&]() -> fs::path {
            if (i + 1 >= argc) return {};
            return fs::path(argv[++i]);
        };
        if (key == "--crash-dir") args.crash_dir = next();
        else if (key == "--diagnostic-log") args.diagnostic_log = next();
    }
    return args;
}

int run_preview_job(const fs::path& job_path, const fs::path& report_path) {
    try {
        cdmw_native_diag::event(
            "preview_job_start",
            {
                {"job_path", cdmw_native_diag::path_to_utf8(job_path)},
                {"report_path", cdmw_native_diag::path_to_utf8(report_path)},
                {"service_job_count", std::to_string(g_service_job_count)}
            });
        write_text(report_path, preview_report_for_job(job_path));
        const cdmw_native_diag::ProcessMemorySnapshot memory = cdmw_native_diag::current_process_memory();
        cdmw_native_diag::event(
            "preview_job_complete",
            {
                {"job_path", cdmw_native_diag::path_to_utf8(job_path)},
                {"report_path", cdmw_native_diag::path_to_utf8(report_path)},
                {"decoded_cache_entries", std::to_string(decoded_entry_cache_entries())},
                {"decoded_cache_bytes", std::to_string(decoded_entry_cache_bytes())},
                {"decoded_cache_hits", std::to_string(decoded_entry_cache_hits())},
                {"decoded_cache_misses", std::to_string(decoded_entry_cache_misses())},
                {"decoded_cache_evictions", std::to_string(decoded_entry_cache_evictions())},
                {"service_job_count", std::to_string(g_service_job_count)},
                {"service_recycle_reason", service_recycle_reason(memory)}
            });
        return 0;
    } catch (const std::exception& exc) {
        std::ostringstream out;
        out << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\""
            << json_escape(exc.what()) << "\",\"fallback_reason\":\"" << json_escape(exc.what()) << "\"}";
        try {
            write_text(report_path, out.str());
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        cdmw_native_diag::event("preview_job_error", {{"job_path", cdmw_native_diag::path_to_utf8(job_path)}, {"message", exc.what()}});
        return 2;
    }
}

static std::vector<std::string> name_search_tokens(const std::string& text) {
    std::vector<std::string> tokens;
    std::string current;
    for (unsigned char raw_ch : text) {
        if (std::isalnum(raw_ch)) {
            current.push_back(static_cast<char>(std::tolower(raw_ch)));
        } else if (!current.empty()) {
            tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) tokens.push_back(current);
    return tokens;
}

static const std::vector<std::pair<std::string, std::vector<std::string>>>& name_search_token_aliases() {
    static const std::vector<std::pair<std::string, std::vector<std::string>>> aliases = {
        {"armor", {"armour"}},
        {"armour", {"armor"}},
        {"helmet", {"helm"}},
        {"helm", {"helmet"}},
        {"pickaxe", {"axe"}},
        {"crossbow", {"bow"}},
        {"treasurebox", {"treasure", "box"}},
        {"campfire", {"camp", "fire"}},
        {"candlestick", {"candle", "lamp"}},
    };
    return aliases;
}

static void add_name_search_token(
    std::unordered_map<std::string, std::vector<std::uint32_t>>& token_rows,
    const std::string& token,
    std::uint32_t row
) {
    const std::string normalized = lower_copy(token);
    if (normalized.size() <= 1) return;
    token_rows[normalized].push_back(row);
    for (const auto& [source, aliases] : name_search_token_aliases()) {
        if (source.size() > 4 && normalized.find(source) != std::string::npos && source != normalized) {
            token_rows[source].push_back(row);
        }
        if (normalized == source || (source.size() > 4 && normalized.find(source) != std::string::npos)) {
            for (const std::string& alias : aliases) {
                if (alias.size() > 1) token_rows[alias].push_back(row);
            }
        }
    }
}

static std::vector<std::string> split_tsv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    for (char ch : line) {
        if (ch == '\t') {
            fields.push_back(current);
            current.clear();
        } else {
            current.push_back(ch);
        }
    }
    fields.push_back(current);
    return fields;
}

template <typename T>
static void write_pod(std::ofstream& out, T value) {
    out.write(reinterpret_cast<const char*>(&value), sizeof(T));
}

int run_name_index_job(const fs::path& input_tsv_path, const fs::path& output_bin_path, const fs::path& report_path) {
    const auto started = std::chrono::steady_clock::now();
    std::uint32_t entry_count = 0;
    std::unordered_map<std::string, std::vector<std::uint32_t>> token_rows;
    try {
        std::ifstream in(input_tsv_path, std::ios::binary);
        if (!in) throw std::runtime_error("could not open name-search input TSV");
        std::string line;
        while (std::getline(in, line)) {
            const std::vector<std::string> fields = split_tsv_line(line);
            if (fields.size() < 3) continue;
            std::uint32_t row = 0;
            try {
                row = static_cast<std::uint32_t>(std::stoul(fields[0]));
            } catch (...) {
                continue;
            }
            entry_count = std::max(entry_count, row + 1u);
            std::string text = fields[1] + " " + fields[2];
            if (fields.size() >= 4 && !fields[3].empty()) {
                text += " ";
                text += fields[3];
            }
            std::set<std::string> seen_tokens;
            for (const std::string& token : name_search_tokens(text)) {
                if (!seen_tokens.insert(token).second) continue;
                add_name_search_token(token_rows, token, row);
            }
        }

        fs::create_directories(output_bin_path.parent_path());
        std::ofstream out(output_bin_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("could not write name-search output binary");
        const char magic[8] = {'C', 'D', 'N', 'I', 'D', 'X', '1', '\0'};
        out.write(magic, sizeof(magic));
        write_pod<std::uint32_t>(out, 1u);
        std::vector<std::string> keys;
        keys.reserve(token_rows.size());
        for (const auto& [token, _rows] : token_rows) {
            if (!token.empty() && token.size() <= 65535u) keys.push_back(token);
        }
        std::sort(keys.begin(), keys.end());
        write_pod<std::uint32_t>(out, entry_count);
        write_pod<std::uint32_t>(out, static_cast<std::uint32_t>(keys.size()));
        std::uint64_t posting_count = 0;
        for (const std::string& token : keys) {
            std::vector<std::uint32_t>& rows = token_rows[token];
            std::sort(rows.begin(), rows.end());
            rows.erase(std::unique(rows.begin(), rows.end()), rows.end());
            const auto token_size = static_cast<std::uint16_t>(token.size());
            write_pod<std::uint16_t>(out, token_size);
            out.write(token.data(), token.size());
            write_pod<std::uint32_t>(out, static_cast<std::uint32_t>(rows.size()));
            if (!rows.empty()) {
                out.write(reinterpret_cast<const char*>(rows.data()), static_cast<std::streamsize>(rows.size() * sizeof(std::uint32_t)));
                posting_count += rows.size();
            }
        }
        out.close();
        if (!out) throw std::runtime_error("name-search output binary write failed");
        const double elapsed_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
        std::ostringstream report;
        report << "{"
               << "\"status\":\"ok\","
               << "\"backend\":\"cdmw_preview_core_0.1\","
               << "\"operation\":\"name_index\","
               << "\"entry_count\":" << entry_count << ","
               << "\"token_count\":" << keys.size() << ","
               << "\"posting_count\":" << posting_count << ","
               << "\"elapsed_ms\":" << elapsed_ms << ","
               << "\"output_path\":\"" << json_escape(output_bin_path.string()) << "\""
               << "}";
        write_text(report_path, report.str());
        return 0;
    } catch (const std::exception& exc) {
        std::ostringstream report;
        report << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"operation\":\"name_index\",\"message\":\""
               << json_escape(exc.what()) << "\"}";
        try { write_text(report_path, report.str()); } catch (...) {}
        return 2;
    }
}

std::string extract_line_path(const std::string& line, const std::string& key) {
    std::string value = find_string_value(line, key);
    if (!value.empty()) return value;
    return {};
}

int run_service() {
    cdmw_native_diag::event("service_start");
    std::cout << "{\"event\":\"ready\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        const std::string lowered = lower_copy(line);
        if (lowered.find("\"shutdown\"") != std::string::npos) {
            cdmw_native_diag::event("service_shutdown");
            std::cout << "{\"event\":\"closed\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            return 0;
        }
        if (lowered.find("\"ping\"") != std::string::npos) {
            cdmw_native_diag::event("service_ping");
            std::cout << "{\"event\":\"pong\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            continue;
        }
        const std::string job_path = extract_line_path(line, "job_path");
        const std::string report_path = extract_line_path(line, "report_path");
        if (!job_path.empty() && !report_path.empty()) {
            ++g_service_job_count;
            cdmw_native_diag::event(
                "service_job_dispatch",
                {
                    {"job_path", job_path},
                    {"report_path", report_path},
                    {"service_job_count", std::to_string(g_service_job_count)}
                });
            run_preview_job(fs::path(job_path), fs::path(report_path));
            try {
                std::cout << read_text(fs::path(report_path)) << std::endl;
            } catch (...) {
                cdmw_native_diag::event("service_report_readback_failed", {{"report_path", report_path}});
                std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"report readback failed\"}" << std::endl;
            }
            continue;
        }
        cdmw_native_diag::event("service_unknown_command");
        std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"unknown command\"}" << std::endl;
    }
    cdmw_native_diag::event("service_closed_stdin");
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    CommonArgs common_args = parse_common_args(argc, argv);
    cdmw_native_diag::init("cdmw-preview-core", common_args.crash_dir, common_args.diagnostic_log);
    try {
        if (argc >= 2 && std::string(argv[1]) == "self-test") {
            cdmw_native_diag::event("self_test_ok");
            std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"cdmw_preview_core_0.1\"}\n";
            return 0;
        }
        if (argc >= 2 && std::string(argv[1]) == "--service") {
            return run_service();
        }
        if (argc >= 4 && std::string(argv[1]) == "preview-job") {
            return run_preview_job(fs::path(argv[2]), fs::path(argv[3]));
        }
        if (argc >= 5 && std::string(argv[1]) == "name-index-job") {
            return run_name_index_job(fs::path(argv[2]), fs::path(argv[3]), fs::path(argv[4]));
        }
        std::cerr << "usage: cdmw-preview-core self-test | --service | preview-job <job.json> <report.json> | name-index-job <input.tsv> <output.bin> <report.json>\n";
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
