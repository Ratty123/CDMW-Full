#include <DirectXMath.h>
#include <DirectXTex.h>
#include <Windows.h>
#include <windowsx.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dxgi.h>
#include <wrl/client.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;

static constexpr UINT kVertexStrideBytes = 23u * 4u;
static constexpr float kDefaultYawDegrees = -35.0f;
static constexpr float kDefaultPitchDegrees = 20.0f;
static constexpr float kFitDistance = 3.25f;
static constexpr float kVerticalFovDegrees = 45.0f;
static constexpr float kZoomSteps[] = {0.1f, 0.25f, 0.5f, 0.75f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f, 6.0f, 8.0f, 12.0f, 16.0f};
static constexpr UINT kCdmwSetZoomMessage = WM_APP + 0x431u;
static constexpr UINT kCdmwSetFitMessage = WM_APP + 0x432u;
static constexpr UINT kCdmwResetViewMessage = WM_APP + 0x433u;

struct Args {
    std::wstring backend = L"d3d11";
    fs::path preview_package;
    fs::path status_file;
    std::string theme_background = "#080b0e";
    std::string theme_text = "#c5ced8";
    uintptr_t parent_hwnd = 0;
    bool self_test = false;
};

struct SlotCounts {
    int base = 0;
    int normal = 0;
    int material = 0;
    int height = 0;
    int occlusion = 0;
    int roughness = 0;
    int metalness = 0;
    int specular = 0;
    int detail = 0;
};

struct PreviewBatch {
    int index = 0;
    int vertex_count = 0;
    bool flip_v = false;
    float base_color[3] = {0.78f, 0.48f, 0.34f};
    std::wstring vertex_file;
    std::wstring base_dds;
    std::wstring normal_dds;
    std::wstring material_dds;
    std::wstring occlusion_dds;
    std::wstring roughness_dds;
    std::wstring metalness_dds;
    std::wstring specular_dds;
    std::wstring detail_dds;
    std::wstring height_dds;
    std::wstring base_png;
    std::wstring normal_png;
    std::wstring occlusion_png;
    std::wstring roughness_png;
    std::wstring metalness_png;
    std::wstring specular_png;
    std::wstring height_png;
    float normal_strength = 1.0f;
    float height_amount = 0.0f;
    float roughness_hint = 0.0f;
    float metalness_hint = 0.0f;
    float specular_hint = 0.0f;
    float height_scale_hint = 0.0f;
    ComPtr<ID3D11Buffer> vertex_buffer;
    ComPtr<ID3D11ShaderResourceView> base_srv;
    ComPtr<ID3D11ShaderResourceView> normal_srv;
    ComPtr<ID3D11ShaderResourceView> material_srv;
    ComPtr<ID3D11ShaderResourceView> occlusion_srv;
    ComPtr<ID3D11ShaderResourceView> roughness_srv;
    ComPtr<ID3D11ShaderResourceView> metalness_srv;
    ComPtr<ID3D11ShaderResourceView> specular_srv;
    ComPtr<ID3D11ShaderResourceView> detail_srv;
    ComPtr<ID3D11ShaderResourceView> height_srv;
};

struct ConstantBuffer {
    DirectX::XMFLOAT4X4 mvp;
    DirectX::XMFLOAT4 light_dir;
    DirectX::XMFLOAT4 base_color_flip;
    DirectX::XMFLOAT4 flags;
    DirectX::XMFLOAT4 flags2;
    DirectX::XMFLOAT4 material_params;
    DirectX::XMFLOAT4 material_hints;
    DirectX::XMFLOAT4 flags3;
};

struct RendererStats {
    int batch_count = 0;
    int vertex_count = 0;
    int png_fallback = 0;
    int texture_cache_hits = 0;
    int low_resolution_base_textures = 0;
    int srgb_color_uploads = 0;
    int linear_data_uploads = 0;
    SlotCounts dds_candidates;
    SlotCounts dds_uploaded;
    SlotCounts png_uploaded;
    SlotCounts textures_loaded;
    int material_combiner_active_batches = 0;
    std::map<std::string, int> material_combiner_outputs;
    std::map<std::string, int> material_combiner_decode_modes;
    std::map<std::string, int> dds_upload_formats;
    double manifest_ms = 0.0;
    double geometry_ms = 0.0;
    double texture_ms = 0.0;
    double first_frame_ms = 0.0;
    std::vector<std::string> skipped;
};

struct TextureLoadInfo {
    std::string format_name;
    size_t width = 0;
    size_t height = 0;
};

struct ViewSettings {
    float orbit_sensitivity = 0.22f;
    float pan_sensitivity = 0.60f;
    bool invert_orbit_x = false;
    bool invert_orbit_y = false;
    bool invert_pan_x = false;
    bool invert_pan_y = false;
};

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
    fs::rename(temp, path, ec);
    if (ec) {
        fs::copy_file(temp, path, fs::copy_options::overwrite_existing, ec);
        fs::remove(temp, ec);
    }
    return true;
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
        else if (key == L"--backend") args.backend = next();
        else if (key == L"--preview-package") args.preview_package = next();
        else if (key == L"--status-file") args.status_file = next();
        else if (key == L"--theme-background") args.theme_background = wide_to_utf8(next());
        else if (key == L"--theme-text") args.theme_text = wide_to_utf8(next());
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

static bool json_bool_field(const std::string& object, const std::string& name, bool fallback = false) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(true|false)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    return match[1].str() == "true";
}

static float json_float_field(const std::string& object, const std::string& name, float fallback = 0.0f) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(-?\\d+(?:\\.\\d+)?)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return std::stof(match[1].str());
    } catch (...) {
        return fallback;
    }
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

static std::wstring dds_slot_source(const std::string& object, const std::string& slot) {
    std::regex pattern("\"" + slot + "\"\\s*:\\s*\\{[^{}]*\"source_path\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return L"";
    return utf8_to_wide(json_unescape(match[1].str()));
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

static std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
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
        if (contains_text(descriptor, "gloss") || contains_text(descriptor, "smoothness")) score = std::max(score, 72);
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

static void increment_slot(SlotCounts& counts, const std::string& slot) {
    if (slot == "base") ++counts.base;
    else if (slot == "normal") ++counts.normal;
    else if (slot == "material") ++counts.material;
    else if (slot == "height") ++counts.height;
    else if (slot == "occlusion") ++counts.occlusion;
    else if (slot == "roughness") ++counts.roughness;
    else if (slot == "metalness") ++counts.metalness;
    else if (slot == "specular") ++counts.specular;
    else if (slot == "detail") ++counts.detail;
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

static void parse_base_color(const std::string& object, float out_color[3]) {
    std::regex pattern("\"base_color\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return;
    std::string values = match[1].str();
    std::regex number_pattern("-?\\d+(?:\\.\\d+)?");
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

static std::vector<PreviewBatch> parse_manifest_batches(const fs::path& package_dir, const std::string& manifest, RendererStats& stats) {
    std::vector<PreviewBatch> batches;
    for (const std::string& object : objects_with_key(manifest, "vertex_file")) {
        PreviewBatch batch;
        batch.index = json_int_field(object, "index", static_cast<int>(batches.size()));
        batch.vertex_count = json_int_field(object, "vertex_count", 0);
        batch.flip_v = json_bool_field(object, "texture_flip_vertical", false);
        parse_base_color(object, batch.base_color);
        batch.vertex_file = absolute_from_manifest_path(package_dir, json_string_field(object, "vertex_file"));
        batch.base_dds = dds_slot_source(object, "base");
        std::wstring rich_base_dds = best_material_dds_for_role(object, "base");
        if (!rich_base_dds.empty()) batch.base_dds = rich_base_dds;
        batch.normal_dds = dds_slot_source(object, "normal");
        batch.material_dds = dds_slot_source(object, "material");
        if (batch.material_dds.empty()) batch.material_dds = best_material_dds_for_role(object, "material");
        batch.occlusion_dds = best_material_dds_for_role(object, "occlusion");
        batch.roughness_dds = best_material_dds_for_role(object, "roughness");
        batch.metalness_dds = best_material_dds_for_role(object, "metalness");
        batch.specular_dds = best_material_dds_for_role(object, "specular");
        batch.detail_dds = best_material_dds_for_role(object, "detail");
        batch.height_dds = dds_slot_source(object, "height");
        batch.base_png = texture_slot_relative(package_dir, object, "base");
        batch.normal_png = texture_slot_relative(package_dir, object, "normal");
        batch.occlusion_png = texture_slot_relative(package_dir, object, "occlusion");
        batch.roughness_png = texture_slot_relative(package_dir, object, "roughness");
        batch.metalness_png = texture_slot_relative(package_dir, object, "metalness");
        batch.specular_png = texture_slot_relative(package_dir, object, "specular");
        batch.height_png = texture_slot_relative(package_dir, object, "height");
        batch.normal_strength = std::clamp(json_float_field(object, "normal_strength", 1.0f), 0.0f, 2.0f);
        batch.height_amount = std::clamp(json_float_field(object, "height_amount", 0.0f), 0.0f, 0.16f);
        batch.roughness_hint = std::clamp(json_float_field(object, "roughness", 0.0f), 0.0f, 1.0f);
        batch.metalness_hint = std::clamp(json_float_field(object, "metalness", 0.0f), 0.0f, 1.0f);
        batch.specular_hint = std::clamp(json_float_field(object, "specular", 0.0f), 0.0f, 1.0f);
        batch.height_scale_hint = std::clamp(json_float_field(object, "height_scale", 0.0f), 0.0f, 1.0f);
        if (!batch.base_dds.empty()) increment_slot(stats.dds_candidates, "base");
        if (!batch.normal_dds.empty()) increment_slot(stats.dds_candidates, "normal");
        if (!batch.material_dds.empty()) increment_slot(stats.dds_candidates, "material");
        if (!batch.occlusion_dds.empty()) increment_slot(stats.dds_candidates, "occlusion");
        if (!batch.roughness_dds.empty()) increment_slot(stats.dds_candidates, "roughness");
        if (!batch.metalness_dds.empty()) increment_slot(stats.dds_candidates, "metalness");
        if (!batch.specular_dds.empty()) increment_slot(stats.dds_candidates, "specular");
        if (!batch.detail_dds.empty()) increment_slot(stats.dds_candidates, "detail");
        if (!batch.height_dds.empty()) increment_slot(stats.dds_candidates, "height");
        if (json_bool_field(object, "material_combiner_active", false)) {
            ++stats.material_combiner_active_batches;
        }
        for (const std::string& output : json_string_array_field(object, "material_combiner_outputs")) {
            ++stats.material_combiner_outputs[output];
        }
        for (const std::string& mode : json_string_array_field(object, "material_combiner_decode_modes")) {
            ++stats.material_combiner_decode_modes[mode];
        }
        if (batch.vertex_count > 0 && !batch.vertex_file.empty()) {
            batches.push_back(batch);
        }
    }
    stats.batch_count = static_cast<int>(batches.size());
    stats.vertex_count = json_int_field(manifest, "vertex_count", 0);
    return batches;
}

static ViewSettings parse_view_settings(const std::string& manifest) {
    ViewSettings settings;
    settings.orbit_sensitivity = std::clamp(json_float_field(manifest, "orbit_sensitivity", settings.orbit_sensitivity), 0.001f, 8.0f);
    settings.pan_sensitivity = std::clamp(json_float_field(manifest, "pan_sensitivity", settings.pan_sensitivity), 0.001f, 8.0f);
    settings.invert_orbit_x = json_bool_field(manifest, "invert_orbit_x", settings.invert_orbit_x);
    settings.invert_orbit_y = json_bool_field(manifest, "invert_orbit_y", settings.invert_orbit_y);
    settings.invert_pan_x = json_bool_field(manifest, "invert_pan_x", settings.invert_pan_x);
    settings.invert_pan_y = json_bool_field(manifest, "invert_pan_y", settings.invert_pan_y);
    return settings;
}

static DirectX::XMFLOAT4 parse_hex_color(const std::string& hex, DirectX::XMFLOAT4 fallback) {
    if (hex.size() < 7 || hex[0] != '#') return fallback;
    try {
        int r = std::stoi(hex.substr(1, 2), nullptr, 16);
        int g = std::stoi(hex.substr(3, 2), nullptr, 16);
        int b = std::stoi(hex.substr(5, 2), nullptr, 16);
        return DirectX::XMFLOAT4(r / 255.0f, g / 255.0f, b / 255.0f, 1.0f);
    } catch (...) {
        return fallback;
    }
}

static std::string skipped_json(const std::vector<std::string>& skipped) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < skipped.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(skipped[i]) << "\"";
    }
    out << "]";
    return out.str();
}

static std::string loaded_payload(const RendererStats& stats) {
    std::ostringstream loaded;
    loaded << "{"
           << "\"event\":\"loaded\","
           << "\"backend\":\"D3D11\","
           << "\"batch_count\":" << stats.batch_count << ","
           << "\"vertex_count\":" << stats.vertex_count << ","
           << "\"textures\":" << slot_counts_json(stats.textures_loaded) << ","
           << "\"png_fallback\":" << stats.png_fallback << ","
           << "\"texture_cache_hits\":" << stats.texture_cache_hits << ","
           << "\"low_resolution_base_textures\":" << stats.low_resolution_base_textures << ","
           << "\"srgb_color_uploads\":" << stats.srgb_color_uploads << ","
           << "\"linear_data_uploads\":" << stats.linear_data_uploads << ","
           << "\"png_fallbacks\":" << slot_counts_json(stats.png_uploaded) << ","
           << "\"dds_direct_upload_candidates\":" << slot_counts_json(stats.dds_candidates) << ","
           << "\"dds_direct_uploads\":" << slot_counts_json(stats.dds_uploaded) << ","
           << "\"dds_upload_formats\":" << string_int_map_json(stats.dds_upload_formats) << ","
           << "\"material_combiner_active\":" << stats.material_combiner_active_batches << ","
           << "\"material_combiner_outputs\":" << string_int_map_json(stats.material_combiner_outputs) << ","
           << "\"material_combiner_decode_modes\":" << string_int_map_json(stats.material_combiner_decode_modes) << ","
           << "\"manifest_read_ms\":" << stats.manifest_ms << ","
           << "\"texture_bind_ms\":" << stats.texture_ms << ","
           << "\"geometry_upload_ms\":" << stats.geometry_ms << ","
           << "\"first_frame_ms\":" << stats.first_frame_ms << ","
           << "\"skipped\":" << skipped_json(stats.skipped)
           << "}";
    return loaded.str();
}

static HRESULT compile_shader(const char* source, const char* entry, const char* target, ID3DBlob** blob, std::string& error_text) {
    UINT flags = D3DCOMPILE_ENABLE_STRICTNESS;
#if defined(_DEBUG)
    flags |= D3DCOMPILE_DEBUG;
#endif
    ComPtr<ID3DBlob> errors;
    HRESULT hr = D3DCompile(source, strlen(source), nullptr, nullptr, nullptr, entry, target, flags, 0, blob, errors.GetAddressOf());
    if (FAILED(hr) && errors) {
        error_text.assign(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize());
    }
    return hr;
}

static const char* kShaderSource = R"(
cbuffer Constants : register(b0) {
    row_major float4x4 mvp;
    float4 light_dir;
    float4 base_color_flip;
    float4 flags;
    float4 flags2;
    float4 material_params;
    float4 material_hints;
    float4 flags3;
};
Texture2D base_tex : register(t0);
Texture2D normal_tex : register(t1);
Texture2D material_tex : register(t2);
Texture2D occlusion_tex : register(t3);
Texture2D roughness_tex : register(t4);
Texture2D metalness_tex : register(t5);
Texture2D specular_tex : register(t6);
Texture2D height_tex : register(t7);
Texture2D detail_tex : register(t8);
SamplerState preview_sampler : register(s0);
struct VSIn {
    float3 position : POSITION;
    float3 normal : NORMAL;
    float3 color : COLOR0;
    float2 uv : TEXCOORD0;
    float3 tangent : TANGENT;
    float3 bitangent : BINORMAL;
};
struct VSOut {
    float4 position : SV_POSITION;
    float3 normal : NORMAL;
    float3 color : COLOR0;
    float2 uv : TEXCOORD0;
    float3 tangent : TANGENT;
    float3 bitangent : BINORMAL;
};
float3 srgb_to_linear(float3 color) {
    return pow(saturate(color), 2.2);
}
float3 linear_to_srgb(float3 color) {
    return pow(saturate(color), 1.0 / 2.2);
}
VSOut vs_main(VSIn input) {
    VSOut output;
    output.position = mul(float4(input.position, 1.0), mvp);
    output.normal = normalize(input.normal);
    output.color = input.color;
    output.uv = input.uv;
    output.tangent = normalize(input.tangent);
    output.bitangent = normalize(input.bitangent);
    return output;
}
float4 ps_main(VSOut input) : SV_TARGET {
    float2 uv = input.uv;
    if (base_color_flip.w > 0.5) {
        uv.y = 1.0 - uv.y;
    }
    float3 albedo = srgb_to_linear(max(input.color, base_color_flip.rgb));
    if (flags.x > 0.5) {
        albedo = base_tex.Sample(preview_sampler, uv).rgb;
    }
    float3 n = normalize(input.normal);
    float3 t = input.tangent;
    float3 b = input.bitangent;
    if (dot(t, t) < 1e-5) {
        t = float3(1.0, 0.0, 0.0);
    } else {
        t = normalize(t);
    }
    if (dot(b, b) < 1e-5) {
        b = normalize(cross(n, t));
    } else {
        b = normalize(b);
    }
    if (flags.y > 0.5) {
        float3 sampled = normal_tex.Sample(preview_sampler, uv).xyz;
        float2 xy = sampled.xy * 2.0 - 1.0;
        xy.y = -xy.y;
        float z = sqrt(saturate(1.0 - dot(xy, xy)));
        float3 mapped = normalize(float3(xy, z));
        float3 normal_mapped = normalize(t * mapped.x + b * mapped.y + n * mapped.z);
        n = normalize(lerp(n, normal_mapped, saturate(material_params.x)));
    }
    float ao = 1.0;
    float roughness = 0.55;
    float specular = 0.15;
    float metalness = 0.0;
    if (material_hints.x > 0.02) {
        roughness = lerp(roughness, material_hints.x, 0.32);
    }
    if (material_hints.y > 0.02) {
        metalness = max(metalness, material_hints.y);
    }
    if (material_hints.z > 0.02) {
        specular = max(specular, material_hints.z);
    }
    if (flags.z > 0.5) {
        float4 m = material_tex.Sample(preview_sampler, uv);
        ao = min(ao, max(0.35, m.r));
        roughness = saturate(m.g);
        metalness = max(metalness, saturate(m.b) * 0.55);
        specular = saturate(max(m.a, m.b * 0.55));
    }
    if (flags2.x > 0.5) {
        ao = min(ao, max(0.35, occlusion_tex.Sample(preview_sampler, uv).r));
    }
    if (flags2.y > 0.5) {
        roughness = saturate(roughness_tex.Sample(preview_sampler, uv).r);
    }
    if (flags2.z > 0.5) {
        metalness = saturate(metalness_tex.Sample(preview_sampler, uv).r);
    }
    if (flags2.w > 0.5) {
        float3 spec_sample = specular_tex.Sample(preview_sampler, uv).rgb;
        float spec_value = max(spec_sample.r, max(spec_sample.g, spec_sample.b));
        specular = saturate(max(specular, spec_value * 0.88));
        if (flags2.y < 0.5) {
            roughness = min(roughness, lerp(0.72, 0.24, spec_value));
        }
    }
    if (flags3.x > 0.5) {
        float3 detail_sample = detail_tex.Sample(preview_sampler, uv).rgb;
        float detail_value = max(detail_sample.r, max(detail_sample.g, detail_sample.b));
        roughness = saturate(lerp(roughness, roughness * (0.86 + detail_value * 0.30), 0.36));
        if (flags2.w < 0.5) {
            specular = saturate(max(specular, detail_value * 0.16));
        }
    }
    float height_value = 0.5;
    if (flags.w > 0.5) {
        height_value = height_tex.Sample(preview_sampler, uv).r;
        float2 duv_x = ddx(uv);
        float2 duv_y = ddy(uv);
        if (dot(duv_x, duv_x) < 1e-8) {
            duv_x = float2(1.0 / 1024.0, 0.0);
        }
        if (dot(duv_y, duv_y) < 1e-8) {
            duv_y = float2(0.0, 1.0 / 1024.0);
        }
        float hx = height_tex.Sample(preview_sampler, uv + duv_x).r - height_tex.Sample(preview_sampler, uv - duv_x).r;
        float hy = height_tex.Sample(preview_sampler, uv + duv_y).r - height_tex.Sample(preview_sampler, uv - duv_y).r;
        float height_strength = saturate((material_params.y + material_hints.w * 0.04) * 8.0);
        float3 height_normal = normalize(n - t * hx * height_strength * 2.4 + b * hy * height_strength * 2.4);
        n = normalize(lerp(n, height_normal, height_strength));
        float relief = (height_value - 0.5) * saturate(material_params.y * 10.0);
        roughness = saturate(roughness - relief * 0.10);
    }
    float3 l = normalize(light_dir.xyz);
    float ndotl = saturate(dot(n, l));
    float3 view_dir = float3(0.0, 0.0, -1.0);
    float3 h = normalize(l - view_dir);
    float shine_power = lerp(96.0, 10.0, roughness);
    float highlight = pow(saturate(dot(n, h)), shine_power) * lerp(specular, max(specular, 0.72), metalness);
    float height_light = lerp(1.0 - material_params.y, 1.0 + material_params.y, height_value);
    float3 diffuse = albedo * (0.28 + ndotl * 0.82) * ao * height_light * lerp(1.0, 0.72, metalness);
    float3 specular_color = lerp(highlight.xxx, highlight.xxx * max(albedo, 0.12), metalness);
    float3 color = diffuse + specular_color;
    return float4(linear_to_srgb(color), 1.0);
}
)";

class Renderer {
public:
    Renderer(HWND hwnd, const Args& args, std::vector<PreviewBatch> batches, RendererStats& stats, ViewSettings view_settings)
        : hwnd_(hwnd), args_(args), batches_(std::move(batches)), stats_(stats), view_settings_(view_settings) {}

    bool initialize() {
        RECT rect{};
        GetClientRect(hwnd_, &rect);
        width_ = std::max<LONG>(1, rect.right - rect.left);
        height_ = std::max<LONG>(1, rect.bottom - rect.top);

        DXGI_SWAP_CHAIN_DESC swap_desc{};
        swap_desc.BufferCount = 2;
        swap_desc.BufferDesc.Width = static_cast<UINT>(width_);
        swap_desc.BufferDesc.Height = static_cast<UINT>(height_);
        swap_desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        swap_desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        swap_desc.OutputWindow = hwnd_;
        swap_desc.SampleDesc.Count = 1;
        swap_desc.Windowed = TRUE;
        swap_desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

        D3D_FEATURE_LEVEL requested[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
        HRESULT hr = D3D11CreateDeviceAndSwapChain(
            nullptr,
            D3D_DRIVER_TYPE_HARDWARE,
            nullptr,
            0,
            requested,
            2,
            D3D11_SDK_VERSION,
            &swap_desc,
            swap_chain_.GetAddressOf(),
            device_.GetAddressOf(),
            &feature_level_,
            context_.GetAddressOf());
        if (FAILED(hr)) {
            stats_.skipped.push_back("D3D11CreateDeviceAndSwapChain failed");
            return false;
        }
        return create_render_targets() && create_pipeline() && upload_batches();
    }

    bool handle_window_message(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result) {
        switch (msg) {
        case kCdmwSetZoomMessage:
            set_zoom_factor(static_cast<float>(wparam) / 1000.0f);
            result = 0;
            return true;
        case kCdmwSetFitMessage:
            set_fit_to_view(wparam != 0);
            result = 0;
            return true;
        case kCdmwResetViewMessage:
            reset_view();
            result = 0;
            return true;
        case WM_LBUTTONDBLCLK:
            reset_view();
            result = 0;
            return true;
        case WM_LBUTTONDOWN:
        case WM_MBUTTONDOWN:
        case WM_RBUTTONDOWN:
            begin_mouse_drag(msg, wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            result = 0;
            return true;
        case WM_MOUSEMOVE:
            update_mouse_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            result = 0;
            return drag_mode_ != 0;
        case WM_LBUTTONUP:
        case WM_MBUTTONUP:
        case WM_RBUTTONUP:
            end_mouse_drag(msg);
            result = 0;
            return true;
        case WM_CAPTURECHANGED:
            drag_mode_ = 0;
            drag_button_ = 0;
            return false;
        case WM_MOUSEWHEEL:
            apply_wheel_delta(GET_WHEEL_DELTA_WPARAM(wparam));
            result = 0;
            return true;
        default:
            return false;
        }
    }

    void render() {
        if (!context_ || !swap_chain_) return;
        resize_if_needed();
        if (!first_frame_started_) {
            first_frame_timer_ = std::chrono::steady_clock::now();
            first_frame_started_ = true;
        }
        float clear[4] = {clear_color_.x, clear_color_.y, clear_color_.z, 1.0f};
        context_->OMSetRenderTargets(1, render_target_.GetAddressOf(), depth_view_.Get());
        context_->ClearRenderTargetView(render_target_.Get(), clear);
        context_->ClearDepthStencilView(depth_view_.Get(), D3D11_CLEAR_DEPTH, 1.0f, 0);
        D3D11_VIEWPORT viewport{};
        viewport.Width = static_cast<float>(width_);
        viewport.Height = static_cast<float>(height_);
        viewport.MinDepth = 0.0f;
        viewport.MaxDepth = 1.0f;
        context_->RSSetViewports(1, &viewport);
        context_->IASetInputLayout(input_layout_.Get());
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
        context_->PSSetSamplers(0, 1, sampler_.GetAddressOf());
        context_->RSSetState(rasterizer_.Get());
        context_->OMSetDepthStencilState(depth_state_.Get(), 0);

        DirectX::XMMATRIX world = DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(pitch_),
                DirectX::XMConvertToRadians(yaw_),
                0.0f)
            * DirectX::XMMatrixTranslation(pan_x_, pan_y_, pan_z_);
        DirectX::XMMATRIX view = DirectX::XMMatrixLookAtLH(
            DirectX::XMVectorSet(0.0f, 0.0f, -distance_, 1.0f),
            DirectX::XMVectorSet(0.0f, 0.0f, 0.0f, 1.0f),
            DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f));
        DirectX::XMMATRIX projection = DirectX::XMMatrixPerspectiveFovLH(
            DirectX::XMConvertToRadians(kVerticalFovDegrees),
            static_cast<float>(width_) / std::max(1.0f, static_cast<float>(height_)),
            0.05f,
            100.0f);
        DirectX::XMMATRIX mvp = world * view * projection;

        for (PreviewBatch& batch : batches_) {
            if (!batch.vertex_buffer || batch.vertex_count <= 0) continue;
            UINT stride = kVertexStrideBytes;
            UINT offset = 0;
            context_->IASetVertexBuffers(0, 1, batch.vertex_buffer.GetAddressOf(), &stride, &offset);
            ConstantBuffer constants{};
            DirectX::XMStoreFloat4x4(&constants.mvp, mvp);
            constants.light_dir = DirectX::XMFLOAT4(-0.35f, 0.45f, -0.82f, 0.0f);
            constants.base_color_flip = DirectX::XMFLOAT4(batch.base_color[0], batch.base_color[1], batch.base_color[2], batch.flip_v ? 1.0f : 0.0f);
            constants.flags = DirectX::XMFLOAT4(
                batch.base_srv ? 1.0f : 0.0f,
                batch.normal_srv ? 1.0f : 0.0f,
                batch.material_srv ? 1.0f : 0.0f,
                batch.height_srv ? 1.0f : 0.0f);
            constants.flags2 = DirectX::XMFLOAT4(
                batch.occlusion_srv ? 1.0f : 0.0f,
                batch.roughness_srv ? 1.0f : 0.0f,
                batch.metalness_srv ? 1.0f : 0.0f,
                batch.specular_srv ? 1.0f : 0.0f);
            constants.material_params = DirectX::XMFLOAT4(
                batch.normal_strength,
                batch.height_amount,
                0.0f,
                0.0f);
            constants.material_hints = DirectX::XMFLOAT4(
                batch.roughness_hint,
                batch.metalness_hint,
                batch.specular_hint,
                batch.height_scale_hint);
            constants.flags3 = DirectX::XMFLOAT4(
                batch.detail_srv ? 1.0f : 0.0f,
                0.0f,
                0.0f,
                0.0f);
            context_->UpdateSubresource(constants_.Get(), 0, nullptr, &constants, 0, 0);
            context_->VSSetConstantBuffers(0, 1, constants_.GetAddressOf());
            context_->PSSetConstantBuffers(0, 1, constants_.GetAddressOf());
            ID3D11ShaderResourceView* srvs[9] = {
                batch.base_srv.Get(),
                batch.normal_srv.Get(),
                batch.material_srv.Get(),
                batch.occlusion_srv.Get(),
                batch.roughness_srv.Get(),
                batch.metalness_srv.Get(),
                batch.specular_srv.Get(),
                batch.height_srv.Get(),
                batch.detail_srv.Get(),
            };
            context_->PSSetShaderResources(0, 9, srvs);
            context_->Draw(static_cast<UINT>(batch.vertex_count), 0);
            ID3D11ShaderResourceView* clear_srvs[9] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
            context_->PSSetShaderResources(0, 9, clear_srvs);
        }
        swap_chain_->Present(1, 0);
        if (!first_frame_reported_) {
            stats_.first_frame_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - first_frame_timer_).count();
            write_status(args_.status_file, loaded_payload(stats_));
            first_frame_reported_ = true;
        }
    }

private:
    static float current_display_scale(float distance) {
        return std::max(0.1f, kFitDistance / std::max(distance, 0.01f));
    }

    float world_units_per_pixel() const {
        float viewport_height = std::max(1.0f, static_cast<float>(height_));
        float visible_height = 2.0f * std::max(distance_, 0.1f) * std::tan(DirectX::XMConvertToRadians(kVerticalFovDegrees) * 0.5f);
        return visible_height / viewport_height;
    }

    void reset_view() {
        yaw_ = kDefaultYawDegrees;
        pitch_ = kDefaultPitchDegrees;
        fit_to_view_ = true;
        zoom_factor_ = 1.0f;
        distance_ = kFitDistance;
        pan_x_ = 0.0f;
        pan_y_ = 0.0f;
        pan_z_ = 0.0f;
        drag_mode_ = 0;
        drag_button_ = 0;
        if (GetCapture() == hwnd_) ReleaseCapture();
    }

    void set_zoom_factor(float zoom_factor) {
        zoom_factor_ = std::clamp(zoom_factor, 0.1f, 16.0f);
        fit_to_view_ = false;
        distance_ = kFitDistance / zoom_factor_;
    }

    void set_fit_to_view(bool fit_to_view) {
        fit_to_view_ = fit_to_view;
        distance_ = fit_to_view_ ? kFitDistance : kFitDistance / std::max(zoom_factor_, 0.1f);
    }

    void begin_mouse_drag(UINT msg, WPARAM wparam, int x, int y) {
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool pan_requested = msg == WM_MBUTTONDOWN || msg == WM_RBUTTONDOWN || (msg == WM_LBUTTONDOWN && shift_down);
        drag_mode_ = pan_requested ? 2 : (msg == WM_LBUTTONDOWN ? 1 : 0);
        drag_button_ = msg;
        last_mouse_x_ = x;
        last_mouse_y_ = y;
        if (drag_mode_ != 0) SetCapture(hwnd_);
    }

    void update_mouse_drag(int x, int y) {
        if (drag_mode_ == 0) return;
        int delta_x = x - last_mouse_x_;
        int delta_y = y - last_mouse_y_;
        last_mouse_x_ = x;
        last_mouse_y_ = y;
        if (delta_x == 0 && delta_y == 0) return;
        if (drag_mode_ == 1) {
            float orbit_sign_x = view_settings_.invert_orbit_x ? -1.0f : 1.0f;
            float orbit_sign_y = view_settings_.invert_orbit_y ? -1.0f : 1.0f;
            yaw_ += static_cast<float>(delta_x) * view_settings_.orbit_sensitivity * orbit_sign_x;
            pitch_ = std::clamp(
                pitch_ + static_cast<float>(delta_y) * view_settings_.orbit_sensitivity * orbit_sign_y,
                -89.0f,
                89.0f);
        } else if (drag_mode_ == 2) {
            float units_per_pixel = world_units_per_pixel();
            float horizontal_sign = view_settings_.invert_pan_x ? -1.0f : 1.0f;
            float vertical_sign = view_settings_.invert_pan_y ? 1.0f : -1.0f;
            pan_x_ += static_cast<float>(delta_x) * units_per_pixel * view_settings_.pan_sensitivity * horizontal_sign;
            pan_y_ += static_cast<float>(delta_y) * units_per_pixel * view_settings_.pan_sensitivity * vertical_sign;
        }
    }

    void end_mouse_drag(UINT msg) {
        bool release = false;
        if (drag_button_ == WM_LBUTTONDOWN && msg == WM_LBUTTONUP) release = true;
        if (drag_button_ == WM_MBUTTONDOWN && msg == WM_MBUTTONUP) release = true;
        if (drag_button_ == WM_RBUTTONDOWN && msg == WM_RBUTTONUP) release = true;
        if (!release) return;
        drag_mode_ = 0;
        drag_button_ = 0;
        if (GetCapture() == hwnd_) ReleaseCapture();
    }

    void apply_wheel_delta(int wheel_delta) {
        if (wheel_delta == 0) return;
        int step = wheel_delta > 0 ? 1 : -1;
        float current_zoom = fit_to_view_ ? current_display_scale(distance_) : zoom_factor_;
        size_t closest = 0;
        float best_distance = std::abs(kZoomSteps[0] - current_zoom);
        for (size_t index = 1; index < ARRAYSIZE(kZoomSteps); ++index) {
            float candidate = std::abs(kZoomSteps[index] - current_zoom);
            if (candidate < best_distance) {
                best_distance = candidate;
                closest = index;
            }
        }
        int next_index = std::clamp(static_cast<int>(closest) + step, 0, static_cast<int>(ARRAYSIZE(kZoomSteps)) - 1);
        fit_to_view_ = false;
        zoom_factor_ = kZoomSteps[next_index];
        distance_ = kFitDistance / zoom_factor_;
    }

    bool create_render_targets() {
        ComPtr<ID3D11Texture2D> back_buffer;
        HRESULT hr = swap_chain_->GetBuffer(0, IID_PPV_ARGS(back_buffer.GetAddressOf()));
        if (FAILED(hr)) return false;
        hr = device_->CreateRenderTargetView(back_buffer.Get(), nullptr, render_target_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_TEXTURE2D_DESC depth_desc{};
        depth_desc.Width = static_cast<UINT>(width_);
        depth_desc.Height = static_cast<UINT>(height_);
        depth_desc.MipLevels = 1;
        depth_desc.ArraySize = 1;
        depth_desc.Format = DXGI_FORMAT_D24_UNORM_S8_UINT;
        depth_desc.SampleDesc.Count = 1;
        depth_desc.BindFlags = D3D11_BIND_DEPTH_STENCIL;
        ComPtr<ID3D11Texture2D> depth_texture;
        hr = device_->CreateTexture2D(&depth_desc, nullptr, depth_texture.GetAddressOf());
        if (FAILED(hr)) return false;
        return SUCCEEDED(device_->CreateDepthStencilView(depth_texture.Get(), nullptr, depth_view_.GetAddressOf()));
    }

    bool resize_if_needed() {
        RECT rect{};
        GetClientRect(hwnd_, &rect);
        LONG next_width = std::max<LONG>(1, rect.right - rect.left);
        LONG next_height = std::max<LONG>(1, rect.bottom - rect.top);
        if (next_width == width_ && next_height == height_) {
            return true;
        }
        width_ = next_width;
        height_ = next_height;
        if (context_) {
            ID3D11RenderTargetView* null_target = nullptr;
            context_->OMSetRenderTargets(1, &null_target, nullptr);
        }
        render_target_.Reset();
        depth_view_.Reset();
        HRESULT hr = swap_chain_->ResizeBuffers(0, static_cast<UINT>(width_), static_cast<UINT>(height_), DXGI_FORMAT_UNKNOWN, 0);
        if (FAILED(hr)) {
            stats_.skipped.push_back("swap chain resize failed");
            return false;
        }
        return create_render_targets();
    }

    bool create_pipeline() {
        clear_color_ = parse_hex_color(args_.theme_background, DirectX::XMFLOAT4(0.03f, 0.04f, 0.05f, 1.0f));
        std::string shader_error;
        ComPtr<ID3DBlob> vs_blob;
        ComPtr<ID3DBlob> ps_blob;
        if (FAILED(compile_shader(kShaderSource, "vs_main", "vs_4_0", vs_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("vertex shader compile failed: " + shader_error);
            return false;
        }
        if (FAILED(compile_shader(kShaderSource, "ps_main", "ps_4_0", ps_blob.GetAddressOf(), shader_error))) {
            stats_.skipped.push_back("pixel shader compile failed: " + shader_error);
            return false;
        }
        HRESULT hr = device_->CreateVertexShader(vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), nullptr, vertex_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        hr = device_->CreatePixelShader(ps_blob->GetBufferPointer(), ps_blob->GetBufferSize(), nullptr, pixel_shader_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_INPUT_ELEMENT_DESC layout[] = {
            {"POSITION", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 0, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"NORMAL", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 3 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"COLOR", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 6 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"TEXCOORD", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 9 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"TANGENT", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 11 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
            {"BINORMAL", 0, DXGI_FORMAT_R32G32B32_FLOAT, 0, 14 * 4, D3D11_INPUT_PER_VERTEX_DATA, 0},
        };
        hr = device_->CreateInputLayout(layout, ARRAYSIZE(layout), vs_blob->GetBufferPointer(), vs_blob->GetBufferSize(), input_layout_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_BUFFER_DESC cb_desc{};
        cb_desc.ByteWidth = sizeof(ConstantBuffer);
        cb_desc.Usage = D3D11_USAGE_DEFAULT;
        cb_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        hr = device_->CreateBuffer(&cb_desc, nullptr, constants_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_SAMPLER_DESC sampler_desc{};
        sampler_desc.Filter = D3D11_FILTER_ANISOTROPIC;
        sampler_desc.AddressU = D3D11_TEXTURE_ADDRESS_WRAP;
        sampler_desc.AddressV = D3D11_TEXTURE_ADDRESS_WRAP;
        sampler_desc.AddressW = D3D11_TEXTURE_ADDRESS_WRAP;
        sampler_desc.MipLODBias = -0.85f;
        sampler_desc.MaxAnisotropy = 16;
        sampler_desc.MaxLOD = D3D11_FLOAT32_MAX;
        hr = device_->CreateSamplerState(&sampler_desc, sampler_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_RASTERIZER_DESC raster_desc{};
        raster_desc.FillMode = D3D11_FILL_SOLID;
        raster_desc.CullMode = D3D11_CULL_NONE;
        raster_desc.DepthClipEnable = TRUE;
        hr = device_->CreateRasterizerState(&raster_desc, rasterizer_.GetAddressOf());
        if (FAILED(hr)) return false;
        D3D11_DEPTH_STENCIL_DESC depth_desc{};
        depth_desc.DepthEnable = TRUE;
        depth_desc.DepthWriteMask = D3D11_DEPTH_WRITE_MASK_ALL;
        depth_desc.DepthFunc = D3D11_COMPARISON_LESS_EQUAL;
        return SUCCEEDED(device_->CreateDepthStencilState(&depth_desc, depth_state_.GetAddressOf()));
    }

    bool upload_batches() {
        auto geometry_start = std::chrono::steady_clock::now();
        for (PreviewBatch& batch : batches_) {
            std::vector<uint8_t> data = read_binary(batch.vertex_file);
            const size_t expected = static_cast<size_t>(batch.vertex_count) * kVertexStrideBytes;
            if (data.size() < expected || expected == 0) {
                stats_.skipped.push_back("geometry missing/truncated:" + wide_to_utf8(batch.vertex_file));
                continue;
            }
            D3D11_BUFFER_DESC desc{};
            desc.ByteWidth = static_cast<UINT>(expected);
            desc.Usage = D3D11_USAGE_DEFAULT;
            desc.BindFlags = D3D11_BIND_VERTEX_BUFFER;
            D3D11_SUBRESOURCE_DATA init{};
            init.pSysMem = data.data();
            HRESULT hr = device_->CreateBuffer(&desc, &init, batch.vertex_buffer.GetAddressOf());
            if (FAILED(hr)) {
                stats_.skipped.push_back("vertex buffer upload failed:" + std::to_string(batch.index));
            }
        }
        stats_.geometry_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - geometry_start).count();

        auto texture_start = std::chrono::steady_clock::now();
        for (PreviewBatch& batch : batches_) {
            load_batch_texture(batch.base_dds, batch.base_png, batch.base_srv, "base");
            load_batch_texture(batch.normal_dds, batch.normal_png, batch.normal_srv, "normal");
            load_batch_texture(batch.material_dds, L"", batch.material_srv, "material");
            load_batch_texture(batch.occlusion_dds, batch.occlusion_png, batch.occlusion_srv, "occlusion");
            load_batch_texture(batch.roughness_dds, batch.roughness_png, batch.roughness_srv, "roughness");
            load_batch_texture(batch.metalness_dds, batch.metalness_png, batch.metalness_srv, "metalness");
            load_batch_texture(batch.specular_dds, batch.specular_png, batch.specular_srv, "specular");
            load_batch_texture(batch.detail_dds, L"", batch.detail_srv, "detail");
            load_batch_texture(batch.height_dds, batch.height_png, batch.height_srv, "height");
        }
        stats_.texture_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - texture_start).count();
        return true;
    }

    void load_batch_texture(
        const std::wstring& dds_path,
        const std::wstring& png_fallback,
        ComPtr<ID3D11ShaderResourceView>& target,
        const char* slot) {
        const std::string slot_name(slot);
        const DirectX::CREATETEX_FLAGS create_flags =
            slot_name == "base" ? DirectX::CREATETEX_FORCE_SRGB : DirectX::CREATETEX_IGNORE_SRGB;
        if (!dds_path.empty() && fs::is_regular_file(fs::path(dds_path))) {
            TextureLoadInfo info{};
            if (load_srv_from_file(dds_path, true, target, &info, create_flags)) {
                increment_slot(stats_.dds_uploaded, slot_name);
                increment_slot(stats_.textures_loaded, slot_name);
                if (slot_name == "base") ++stats_.srgb_color_uploads;
                else ++stats_.linear_data_uploads;
                if (!info.format_name.empty()) {
                    ++stats_.dds_upload_formats[info.format_name];
                }
                if (slot_name == "base" && std::max(info.width, info.height) > 0 && std::max(info.width, info.height) < 512) {
                    ++stats_.low_resolution_base_textures;
                }
                return;
            }
            stats_.skipped.push_back(slot_name + " DDS upload failed:" + wide_to_utf8(dds_path));
        }
        if (!png_fallback.empty() && fs::is_regular_file(fs::path(png_fallback))) {
            if (load_srv_from_file(png_fallback, false, target, nullptr, create_flags)) {
                ++stats_.png_fallback;
                increment_slot(stats_.png_uploaded, slot_name);
                increment_slot(stats_.textures_loaded, slot_name);
                if (slot_name == "base") ++stats_.srgb_color_uploads;
                else ++stats_.linear_data_uploads;
                return;
            }
            stats_.skipped.push_back(slot_name + " PNG fallback failed:" + wide_to_utf8(png_fallback));
        }
    }

    bool load_srv_from_file(
        const std::wstring& path,
        bool dds,
        ComPtr<ID3D11ShaderResourceView>& target,
        TextureLoadInfo* info,
        DirectX::CREATETEX_FLAGS create_flags) {
        std::wstring cache_key = (dds ? L"dds|" : L"wic|") + std::to_wstring(static_cast<uint32_t>(create_flags)) + L"|" + path;
        auto cached = srv_cache_.find(cache_key);
        if (cached != srv_cache_.end() && cached->second) {
            target = cached->second;
            ++stats_.texture_cache_hits;
            if (info) {
                auto cached_info = texture_info_cache_.find(cache_key);
                if (cached_info != texture_info_cache_.end()) {
                    *info = cached_info->second;
                }
            }
            return true;
        }
        DirectX::ScratchImage image;
        DirectX::TexMetadata metadata{};
        HRESULT hr = dds
            ? DirectX::LoadFromDDSFile(path.c_str(), DirectX::DDS_FLAGS_NONE, &metadata, image)
            : DirectX::LoadFromWICFile(path.c_str(), DirectX::WIC_FLAGS_NONE, &metadata, image);
        if (FAILED(hr)) return false;
        hr = DirectX::CreateShaderResourceViewEx(
            device_.Get(),
            image.GetImages(),
            image.GetImageCount(),
            metadata,
            D3D11_USAGE_DEFAULT,
            D3D11_BIND_SHADER_RESOURCE,
            0,
            0,
            create_flags,
            target.ReleaseAndGetAddressOf());
        if (SUCCEEDED(hr)) {
            TextureLoadInfo loaded_info{};
            loaded_info.format_name = dxgi_format_name(metadata.format);
            loaded_info.width = metadata.width;
            loaded_info.height = metadata.height;
            srv_cache_[cache_key] = target;
            texture_info_cache_[cache_key] = loaded_info;
            if (info) {
                *info = loaded_info;
            }
        }
        return SUCCEEDED(hr);
    }

    HWND hwnd_{};
    Args args_;
    std::vector<PreviewBatch> batches_;
    RendererStats& stats_;
    ViewSettings view_settings_;
    LONG width_ = 1;
    LONG height_ = 1;
    float yaw_ = kDefaultYawDegrees;
    float pitch_ = kDefaultPitchDegrees;
    bool fit_to_view_ = true;
    float zoom_factor_ = 1.0f;
    float distance_ = kFitDistance;
    float pan_x_ = 0.0f;
    float pan_y_ = 0.0f;
    float pan_z_ = 0.0f;
    int drag_mode_ = 0;
    UINT drag_button_ = 0;
    int last_mouse_x_ = 0;
    int last_mouse_y_ = 0;
    bool first_frame_started_ = false;
    bool first_frame_reported_ = false;
    std::chrono::steady_clock::time_point first_frame_timer_{};
    D3D_FEATURE_LEVEL feature_level_{};
    DirectX::XMFLOAT4 clear_color_{0.03f, 0.04f, 0.05f, 1.0f};
    ComPtr<ID3D11Device> device_;
    ComPtr<ID3D11DeviceContext> context_;
    ComPtr<IDXGISwapChain> swap_chain_;
    ComPtr<ID3D11RenderTargetView> render_target_;
    ComPtr<ID3D11DepthStencilView> depth_view_;
    ComPtr<ID3D11VertexShader> vertex_shader_;
    ComPtr<ID3D11PixelShader> pixel_shader_;
    ComPtr<ID3D11InputLayout> input_layout_;
    ComPtr<ID3D11Buffer> constants_;
    ComPtr<ID3D11SamplerState> sampler_;
    ComPtr<ID3D11RasterizerState> rasterizer_;
    ComPtr<ID3D11DepthStencilState> depth_state_;
    std::map<std::wstring, ComPtr<ID3D11ShaderResourceView>> srv_cache_;
    std::map<std::wstring, TextureLoadInfo> texture_info_cache_;
};

static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam) {
    Renderer* renderer = reinterpret_cast<Renderer*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (renderer) {
        LRESULT handled_result = 0;
        if (renderer->handle_window_message(msg, wparam, lparam, handled_result)) {
            return handled_result;
        }
    }
    if (msg == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wparam, lparam);
}

static int run_host(const Args& args) {
    auto start = std::chrono::steady_clock::now();
    if (args.preview_package.empty() || !fs::is_directory(args.preview_package)) {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"preview package directory is missing\"}");
        return 2;
    }
    write_status(args.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"manifest\",\"message\":\"Loading native D3D11 preview package...\"}");
    std::string manifest = read_text(args.preview_package / L"manifest.json");
    RendererStats stats;
    std::vector<PreviewBatch> batches = parse_manifest_batches(args.preview_package, manifest, stats);
    ViewSettings view_settings = parse_view_settings(manifest);
    stats.manifest_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();

    WNDCLASSW wc{};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"CDMWNativeD3D11PreviewWindow";
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.style = CS_DBLCLKS;
    RegisterClassW(&wc);

    HWND parent_hwnd = reinterpret_cast<HWND>(args.parent_hwnd);
    RECT parent_rect{};
    int window_x = CW_USEDEFAULT;
    int window_y = CW_USEDEFAULT;
    int window_width = 980;
    int window_height = 720;
    DWORD window_style = WS_OVERLAPPEDWINDOW | WS_VISIBLE;
    if (parent_hwnd && IsWindow(parent_hwnd)) {
        GetClientRect(parent_hwnd, &parent_rect);
        window_x = 0;
        window_y = 0;
        window_width = std::max<LONG>(1, parent_rect.right - parent_rect.left);
        window_height = std::max<LONG>(1, parent_rect.bottom - parent_rect.top);
        window_style = WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN;
    } else {
        parent_hwnd = nullptr;
    }

    HWND hwnd = CreateWindowExW(
        0,
        wc.lpszClassName,
        L"CDMW Native D3D11 Preview",
        window_style,
        window_x,
        window_y,
        window_width,
        window_height,
        parent_hwnd,
        nullptr,
        wc.hInstance,
        nullptr);
    if (!hwnd) {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"failed to create preview window\"}");
        return 3;
    }

    write_status(args.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"upload\",\"message\":\"Uploading D3D11 geometry and DDS textures...\"}");
    Renderer renderer(hwnd, args, std::move(batches), stats, view_settings);
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(&renderer));
    if (!renderer.initialize()) {
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 renderer initialization failed\"}");
        return 4;
    }
    write_status(args.status_file, loaded_payload(stats));

    MSG msg{};
    bool running = true;
    auto last_parent_sync = std::chrono::steady_clock::now();
    while (running) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) {
                running = false;
                break;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if (running && parent_hwnd) {
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration<double, std::milli>(now - last_parent_sync).count() >= 100.0) {
                last_parent_sync = now;
                RECT rect{};
                if (!IsWindow(parent_hwnd)) {
                    running = false;
                } else if (GetClientRect(parent_hwnd, &rect)) {
                    int width = std::max<LONG>(1, rect.right - rect.left);
                    int height = std::max<LONG>(1, rect.bottom - rect.top);
                    SetWindowPos(hwnd, nullptr, 0, 0, width, height, SWP_NOZORDER | SWP_NOACTIVATE);
                }
            }
        }
        if (running) {
            renderer.render();
        }
    }
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
    write_status(args.status_file, "{\"event\":\"closed\",\"backend\":\"D3D11\"}");
    return 0;
}

int wmain(int argc, wchar_t** argv) {
    Args args = parse_args(argc, argv);
    if (args.self_test) {
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> context;
        D3D_FEATURE_LEVEL feature{};
        HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, device.GetAddressOf(), &feature, context.GetAddressOf());
        std::cout << "{\"event\":\"self_test\",\"backend\":\"D3D11\",\"ok\":" << (SUCCEEDED(hr) ? "true" : "false") << "}\n";
        return SUCCEEDED(hr) ? 0 : 2;
    }
    if (args.backend != L"d3d11" && args.backend != L"D3D11") {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"only D3D11 backend is supported by this native host\"}");
        return 1;
    }
    return run_host(args);
}
