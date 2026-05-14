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
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "../../common/native_diagnostics.h"

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
static constexpr ULONG_PTR kCdmwCommandCopyData = 0x43444D57u; // "CDMW"
static constexpr ULONG_PTR kCdmwEventCopyData = 0x44334431u; // "D3D1"

struct Args {
    std::wstring backend = L"d3d11";
    fs::path preview_package;
    fs::path status_file;
    std::string theme_background = "#080b0e";
    std::string theme_text = "#c5ced8";
    uintptr_t parent_hwnd = 0;
    bool self_test = false;
    fs::path crash_dir;
    fs::path diagnostic_log;
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
    int source_submesh_index = -1;
    std::wstring identity_file;
    float highlight_strength = 0.0f;
    std::vector<DirectX::XMFLOAT3> cpu_positions;
    std::vector<int> cpu_source_submeshes;
    std::vector<int> cpu_source_vertices;
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

struct EditorCandidate {
    int batch_index = -1;
    int source_submesh_index = -1;
    int source_vertex_index = -1;
    DirectX::XMFLOAT3 position{0.0f, 0.0f, 0.0f};
    float screen_x = 0.0f;
    float screen_y = 0.0f;
    float distance = 0.0f;
    float weight = 1.0f;
};

struct MeshEditState {
    bool enabled = false;
    std::string target_mode = "brush";
    std::string tool = "grab";
    std::string falloff = "smooth";
    float radius_pixels = 24.0f;
    float strength = 0.5f;
    bool show_vertices = false;
    bool drag_active = false;
    int stroke_id = 0;
    int start_x = 0;
    int start_y = 0;
    int last_x = 0;
    int last_y = 0;
    bool previewed = false;
    std::vector<EditorCandidate> drag_candidates;
    std::set<std::pair<int, int>> selected_vertices;
};

struct AlignmentState {
    bool enabled = false;
    std::set<int> selected_source_submeshes;
    std::string hover_axis;
    std::string drag_axis;
    bool drag_active = false;
    bool rotation_drag_active = false;
    bool rotation_drag_roll = false;
    float translation_sensitivity = 0.85f;
    float rotation_degrees_per_pixel = 0.18f;
    int last_x = 0;
    int last_y = 0;
    DirectX::XMFLOAT3 translation_total{0.0f, 0.0f, 0.0f};
    DirectX::XMFLOAT3 rotation_total{0.0f, 0.0f, 0.0f};
};

struct SourcePartInteractionState {
    int hovered_source_submesh = -1;
    bool click_pending = false;
    int click_source_submesh = -1;
    int start_x = 0;
    int start_y = 0;
};

struct ScreenPoint {
    float x = 0.0f;
    float y = 0.0f;
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
    DirectX::XMFLOAT4 render_tuning;
    DirectX::XMFLOAT4 render_tuning2;
    DirectX::XMFLOAT4 editor_tint;
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

struct RenderTuning {
    int max_anisotropy = 16;
    float ambient_strength = 0.55f;
    float diffuse_light_scale = 0.65f;
    float specular_base = 0.05f;
    float specular_max = 0.18f;
    float shininess_min = 28.0f;
    float shininess_max = 72.0f;
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

static std::string json_object_field(const std::string& object, const std::string& name) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\{([^{}]*)\\}");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return "";
    return match[1].str();
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
        std::string editor_identity = json_object_field(object, "editor_identity");
        batch.source_submesh_index = json_int_field(editor_identity, "source_submesh_index", -1);
        batch.identity_file = absolute_from_manifest_path(package_dir, json_string_field(editor_identity, "identity_file"));
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

static RenderTuning parse_render_tuning(const std::string& manifest) {
    RenderTuning tuning;
    tuning.max_anisotropy = std::clamp(json_int_field(manifest, "max_anisotropy", tuning.max_anisotropy), 1, 16);
    tuning.ambient_strength = std::clamp(json_float_field(manifest, "ambient_strength", tuning.ambient_strength), 0.05f, 1.20f);
    tuning.diffuse_light_scale = std::clamp(json_float_field(manifest, "diffuse_light_scale", tuning.diffuse_light_scale), 0.05f, 1.50f);
    tuning.specular_base = std::clamp(json_float_field(manifest, "specular_base", tuning.specular_base), 0.0f, 0.50f);
    tuning.specular_max = std::clamp(json_float_field(manifest, "specular_max", tuning.specular_max), tuning.specular_base, 1.00f);
    tuning.shininess_min = std::clamp(json_float_field(manifest, "shininess_min", tuning.shininess_min), 1.0f, 128.0f);
    tuning.shininess_max = std::clamp(json_float_field(manifest, "shininess_max", tuning.shininess_max), tuning.shininess_min, 256.0f);
    return tuning;
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

static std::string float3_json(const DirectX::XMFLOAT3& value) {
    std::ostringstream out;
    out << "[" << value.x << "," << value.y << "," << value.z << "]";
    return out.str();
}

static std::string float3_delta_json(const DirectX::XMFLOAT3& value) {
    return float3_json(value);
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
    float4 render_tuning;
    float4 render_tuning2;
    float4 editor_tint;
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
    specular = max(specular, render_tuning.z);
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
    specular = min(specular, max(render_tuning.w, render_tuning.z));
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
    float shine_power = lerp(render_tuning2.y, render_tuning2.x, roughness);
    float highlight = pow(saturate(dot(n, h)), shine_power) * lerp(specular, max(specular, 0.72), metalness);
    float height_light = lerp(1.0 - material_params.y, 1.0 + material_params.y, height_value);
    float3 diffuse = albedo * (render_tuning.x + ndotl * render_tuning.y) * ao * height_light * lerp(1.0, 0.72, metalness);
    float3 specular_color = lerp(highlight.xxx, highlight.xxx * max(albedo, 0.12), metalness);
    float3 color = diffuse + specular_color;
    color = lerp(color, editor_tint.rgb, saturate(editor_tint.a));
    return float4(linear_to_srgb(color), 1.0);
}
)";

class Renderer {
public:
    Renderer(HWND hwnd, const Args& args, std::vector<PreviewBatch> batches, RendererStats& stats, ViewSettings view_settings, RenderTuning render_tuning)
        : hwnd_(hwnd), args_(args), batches_(std::move(batches)), stats_(stats), view_settings_(view_settings), render_tuning_(render_tuning) {}

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

    bool load_package(const fs::path& package_dir, const fs::path& status_file, bool reset_view_state) {
        if (package_dir.empty() || !fs::is_directory(package_dir)) {
            write_status(status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"preview package directory is missing\"}");
            cdmw_native_diag::event("package_load_error", {{"reason", "package directory missing"}, {"package_dir", cdmw_native_diag::path_to_utf8(package_dir)}});
            return false;
        }
        args_.preview_package = package_dir;
        if (!status_file.empty()) {
            args_.status_file = status_file;
        }
        cdmw_native_diag::event("package_load_start", {{"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}, {"status_file", cdmw_native_diag::path_to_utf8(args_.status_file)}});
        write_status(args_.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"manifest\",\"message\":\"Loading native D3D11 preview package...\"}");
        auto start = std::chrono::steady_clock::now();
        std::string manifest = read_text(args_.preview_package / L"manifest.json");
        RendererStats next_stats;
        std::vector<PreviewBatch> next_batches = parse_manifest_batches(args_.preview_package, manifest, next_stats);
        ViewSettings next_view_settings = parse_view_settings(manifest);
        RenderTuning next_render_tuning = parse_render_tuning(manifest);
        next_stats.manifest_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        batches_ = std::move(next_batches);
        stats_ = next_stats;
        view_settings_ = next_view_settings;
        render_tuning_ = next_render_tuning;
        first_frame_started_ = false;
        first_frame_reported_ = false;
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_candidates.clear();
        mesh_edit_.selected_vertices.clear();
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.hover_axis.clear();
        alignment_.drag_axis.clear();
        alignment_.selected_source_submeshes.clear();
        source_part_.hovered_source_submesh = -1;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (reset_view_state) {
            reset_view();
        }
        write_status(args_.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"upload\",\"message\":\"Uploading D3D11 geometry and DDS textures...\"}");
        if (!upload_batches()) {
            write_status(args_.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 package reload failed\"}");
            cdmw_native_diag::event("package_load_error", {{"reason", "upload failed"}, {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}});
            return false;
        }
        write_status(args_.status_file, loaded_payload(stats_));
        cdmw_native_diag::event(
            "package_loaded",
            {
                {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)},
                {"batches", std::to_string(stats_.batch_count)},
                {"vertices", std::to_string(stats_.vertex_count)},
                {"dds_uploaded_base", std::to_string(stats_.dds_uploaded.base)},
                {"png_fallback", std::to_string(stats_.png_fallback)}
            });
        return true;
    }

    bool clear_preview(const fs::path& status_file) {
        if (!status_file.empty()) {
            args_.status_file = status_file;
        }
        batches_.clear();
        stats_ = RendererStats{};
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
        first_frame_started_ = true;
        first_frame_reported_ = true;
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_candidates.clear();
        mesh_edit_.selected_vertices.clear();
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.hover_axis.clear();
        alignment_.drag_axis.clear();
        alignment_.selected_source_submeshes.clear();
        source_part_.hovered_source_submesh = -1;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (hwnd_) {
            InvalidateRect(hwnd_, nullptr, FALSE);
        }
        write_status(args_.status_file, "{\"event\":\"cleared\",\"backend\":\"D3D11\",\"message\":\"Native D3D11 preview cleared\"}");
        cdmw_native_diag::event("preview_cleared", {{"status_file", cdmw_native_diag::path_to_utf8(args_.status_file)}});
        return true;
    }

    bool handle_window_message(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result) {
        switch (msg) {
        case WM_COPYDATA:
            result = handle_copy_data(reinterpret_cast<COPYDATASTRUCT*>(lparam)) ? 1 : 0;
            return true;
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
            if (begin_mesh_edit_drag(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                result = 0;
                return true;
            }
            if (begin_alignment_drag(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                result = 0;
                return true;
            }
            begin_source_part_click(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            [[fallthrough]];
        case WM_MBUTTONDOWN:
        case WM_RBUTTONDOWN:
            begin_mouse_drag(msg, wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            result = 0;
            return true;
        case WM_MOUSEMOVE:
            if (update_mesh_edit_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                result = 0;
                return true;
            }
            if (update_alignment_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam), wparam)) {
                result = 0;
                return true;
            }
            update_alignment_hover(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            update_source_part_hover(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            update_mouse_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            result = 0;
            return drag_mode_ != 0;
        case WM_LBUTTONUP:
            if (finish_mesh_edit_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                result = 0;
                return true;
            }
            if (finish_alignment_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam), wparam)) {
                result = 0;
                return true;
            }
            finish_source_part_click(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            [[fallthrough]];
        case WM_MBUTTONUP:
        case WM_RBUTTONUP:
            end_mouse_drag(msg);
            result = 0;
            return true;
        case WM_CAPTURECHANGED:
            cancel_mesh_edit_drag();
            cancel_alignment_drag();
            source_part_.click_pending = false;
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
            constants.render_tuning = DirectX::XMFLOAT4(
                render_tuning_.ambient_strength,
                render_tuning_.diffuse_light_scale,
                render_tuning_.specular_base,
                render_tuning_.specular_max);
            constants.render_tuning2 = DirectX::XMFLOAT4(
                render_tuning_.shininess_min,
                render_tuning_.shininess_max,
                0.0f,
                0.0f);
            constants.editor_tint = DirectX::XMFLOAT4(
                1.0f,
                0.72f,
                0.18f,
                std::clamp(batch.highlight_strength, 0.0f, 0.42f));
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
        draw_alignment_overlay_gdi();
        if (!first_frame_reported_) {
            stats_.first_frame_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - first_frame_timer_).count();
            write_status(args_.status_file, loaded_payload(stats_));
            first_frame_reported_ = true;
            cdmw_native_diag::event(
                "first_frame",
                {
                    {"first_frame_ms", std::to_string(stats_.first_frame_ms)},
                    {"batches", std::to_string(stats_.batch_count)},
                    {"vertices", std::to_string(stats_.vertex_count)}
                });
        }
    }

    void process_pending_commands() {
        if (pending_package_dir_.empty()) return;
        fs::path package_dir = pending_package_dir_;
        fs::path status_file = pending_status_file_;
        bool reset_view_state = pending_reset_view_;
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
        load_package(package_dir, status_file, reset_view_state);
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

    DirectX::XMMATRIX current_world_matrix() const {
        return DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(pitch_),
                DirectX::XMConvertToRadians(yaw_),
                0.0f)
            * DirectX::XMMatrixTranslation(pan_x_, pan_y_, pan_z_);
    }

    DirectX::XMMATRIX current_view_projection_matrix() const {
        DirectX::XMMATRIX view = DirectX::XMMatrixLookAtLH(
            DirectX::XMVectorSet(0.0f, 0.0f, -distance_, 1.0f),
            DirectX::XMVectorSet(0.0f, 0.0f, 0.0f, 1.0f),
            DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f));
        DirectX::XMMATRIX projection = DirectX::XMMatrixPerspectiveFovLH(
            DirectX::XMConvertToRadians(kVerticalFovDegrees),
            static_cast<float>(width_) / std::max(1.0f, static_cast<float>(height_)),
            0.05f,
            100.0f);
        return view * projection;
    }

    DirectX::XMMATRIX current_mvp_matrix() const {
        return current_world_matrix() * current_view_projection_matrix();
    }

    bool project_position(const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR projected = DirectX::XMVector3TransformCoord(source, current_mvp_matrix());
        DirectX::XMFLOAT3 clip{};
        DirectX::XMStoreFloat3(&clip, projected);
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) || !std::isfinite(clip.z)) return false;
        if (clip.z < 0.0f || clip.z > 1.0f) return false;
        screen_x = (clip.x * 0.5f + 0.5f) * static_cast<float>(width_);
        screen_y = (0.5f - clip.y * 0.5f) * static_cast<float>(height_);
        return std::isfinite(screen_x) && std::isfinite(screen_y);
    }

    bool alignment_batch_active(const PreviewBatch& batch) const {
        return alignment_.selected_source_submeshes.empty()
            || alignment_.selected_source_submeshes.find(batch.source_submesh_index) != alignment_.selected_source_submeshes.end();
    }

    bool alignment_handle_origin(DirectX::XMFLOAT3& origin) const {
        bool found = false;
        float min_x = 0.0f;
        float min_y = 0.0f;
        float min_z = 0.0f;
        float max_x = 0.0f;
        float max_y = 0.0f;
        float max_z = 0.0f;
        for (const PreviewBatch& batch : batches_) {
            if (!alignment_batch_active(batch)) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                if (!found) {
                    min_x = max_x = position.x;
                    min_y = max_y = position.y;
                    min_z = max_z = position.z;
                    found = true;
                    continue;
                }
                min_x = std::min(min_x, position.x);
                min_y = std::min(min_y, position.y);
                min_z = std::min(min_z, position.z);
                max_x = std::max(max_x, position.x);
                max_y = std::max(max_y, position.y);
                max_z = std::max(max_z, position.z);
            }
        }
        if (!found) return false;
        origin = DirectX::XMFLOAT3(
            (min_x + max_x) * 0.5f + alignment_.translation_total.x,
            (min_y + max_y) * 0.5f + alignment_.translation_total.y,
            (min_z + max_z) * 0.5f + alignment_.translation_total.z);
        return true;
    }

    std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> alignment_axis_points() const {
        std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> points;
        if (!alignment_.enabled || batches_.empty()) return points;
        DirectX::XMFLOAT3 origin{};
        if (!alignment_handle_origin(origin)) return points;
        float origin_x = 0.0f;
        float origin_y = 0.0f;
        if (!project_position(origin, origin_x, origin_y)) return points;
        constexpr float kAxisExtent = 0.72f;
        const std::pair<const char*, DirectX::XMFLOAT3> axes[] = {
            {"x", DirectX::XMFLOAT3(origin.x + kAxisExtent, origin.y, origin.z)},
            {"y", DirectX::XMFLOAT3(origin.x, origin.y + kAxisExtent, origin.z)},
            {"z", DirectX::XMFLOAT3(origin.x, origin.y, origin.z + kAxisExtent)},
        };
        for (const auto& axis : axes) {
            float end_x = 0.0f;
            float end_y = 0.0f;
            if (!project_position(axis.second, end_x, end_y)) continue;
            points[axis.first] = std::pair<ScreenPoint, ScreenPoint>(
                ScreenPoint{origin_x, origin_y},
                ScreenPoint{end_x, end_y});
        }
        return points;
    }

    static float distance_to_segment(float x, float y, const ScreenPoint& start, const ScreenPoint& end) {
        float vx = end.x - start.x;
        float vy = end.y - start.y;
        float length_sq = vx * vx + vy * vy;
        if (length_sq <= 1e-8f) {
            return std::hypot(x - start.x, y - start.y);
        }
        float t = std::clamp(((x - start.x) * vx + (y - start.y) * vy) / length_sq, 0.0f, 1.0f);
        float closest_x = start.x + vx * t;
        float closest_y = start.y + vy * t;
        return std::hypot(x - closest_x, y - closest_y);
    }

    std::string alignment_axis_at(int x, int y) const {
        if (!alignment_.enabled) return "";
        DirectX::XMFLOAT3 origin{};
        if (alignment_handle_origin(origin)) {
            float origin_x = 0.0f;
            float origin_y = 0.0f;
            if (project_position(origin, origin_x, origin_y) && std::hypot(static_cast<float>(x) - origin_x, static_cast<float>(y) - origin_y) <= 18.0f) {
                return "screen";
            }
        }
        std::string best_axis;
        float best_distance = 20.0f;
        for (const auto& [axis, segment] : alignment_axis_points()) {
            float distance = distance_to_segment(static_cast<float>(x), static_cast<float>(y), segment.first, segment.second);
            if (distance < best_distance) {
                best_axis = axis;
                best_distance = distance;
            }
        }
        return best_axis;
    }

    DirectX::XMFLOAT3 alignment_screen_drag_delta(int delta_x, int delta_y, float units_per_pixel) const {
        DirectX::XMMATRIX rotation = DirectX::XMMatrixRotationRollPitchYaw(
            DirectX::XMConvertToRadians(pitch_),
            DirectX::XMConvertToRadians(yaw_),
            0.0f);
        DirectX::XMVECTOR determinant{};
        DirectX::XMMATRIX inverse_rotation = DirectX::XMMatrixInverse(&determinant, rotation);
        DirectX::XMVECTOR right = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(1.0f, 0.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR up = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR horizontal = DirectX::XMVectorScale(right, static_cast<float>(delta_x) * units_per_pixel);
        DirectX::XMVECTOR vertical = DirectX::XMVectorScale(up, static_cast<float>(delta_y) * units_per_pixel);
        DirectX::XMVECTOR delta = DirectX::XMVectorSubtract(horizontal, vertical);
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, delta);
        return output;
    }

    void send_alignment_vector_event(const char* event_name, const DirectX::XMFLOAT3& value) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\""
            << ",\"x\":" << value.x
            << ",\"y\":" << value.y
            << ",\"z\":" << value.z
            << "}";
        send_json_event(out.str());
    }

    void send_alignment_started_event(const char* mode, const char* axis) const {
        std::ostringstream out;
        out << "{\"event\":\"alignment_drag_started\""
            << ",\"mode\":\"" << json_escape(mode ? mode : "") << "\""
            << ",\"axis\":\"" << json_escape(axis ? axis : "") << "\""
            << "}";
        send_json_event(out.str());
    }

    bool begin_alignment_drag(WPARAM wparam, int x, int y) {
        if (!alignment_.enabled || mesh_edit_.enabled) return false;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        if (alt_down) {
            alignment_.rotation_drag_active = true;
            alignment_.rotation_drag_roll = shift_down;
            alignment_.rotation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            alignment_.last_x = x;
            alignment_.last_y = y;
            SetCapture(hwnd_);
            send_alignment_started_event("rotation", alignment_.rotation_drag_roll ? "roll" : "orbit");
            return true;
        }
        std::string axis = alignment_axis_at(x, y);
        if (axis.empty()) return false;
        alignment_.drag_axis = axis;
        alignment_.hover_axis = axis;
        alignment_.drag_active = true;
        alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.last_x = x;
        alignment_.last_y = y;
        SetCapture(hwnd_);
        send_alignment_started_event("translation", axis.c_str());
        return true;
    }

    bool update_alignment_translation_drag(int x, int y, WPARAM wparam) {
        if (!alignment_.drag_active || alignment_.drag_axis.empty()) return false;
        int delta_x = x - alignment_.last_x;
        int delta_y = y - alignment_.last_y;
        alignment_.last_x = x;
        alignment_.last_y = y;
        if (delta_x == 0 && delta_y == 0) return true;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        float movement_scale = shift_down ? 0.10f : (ctrl_down ? 4.0f : 1.0f);
        float units_per_pixel = world_units_per_pixel() * std::max(0.01f, alignment_.translation_sensitivity) * movement_scale;
        DirectX::XMFLOAT3 delta(0.0f, 0.0f, 0.0f);
        if (alignment_.drag_axis == "screen") {
            delta = alignment_screen_drag_delta(delta_x, delta_y, units_per_pixel);
        } else {
            auto points = alignment_axis_points();
            auto found = points.find(alignment_.drag_axis);
            if (found == points.end()) return true;
            float axis_dx = found->second.second.x - found->second.first.x;
            float axis_dy = found->second.second.y - found->second.first.y;
            float axis_length = std::max(std::hypot(axis_dx, axis_dy), 1.0f);
            float projected_pixels = (static_cast<float>(delta_x) * axis_dx + static_cast<float>(delta_y) * axis_dy) / axis_length;
            float movement = projected_pixels * units_per_pixel;
            if (alignment_.drag_axis == "x") delta.x = movement;
            else if (alignment_.drag_axis == "y") delta.y = movement;
            else if (alignment_.drag_axis == "z") delta.z = movement;
        }
        alignment_.translation_total.x += delta.x;
        alignment_.translation_total.y += delta.y;
        alignment_.translation_total.z += delta.z;
        send_alignment_vector_event("alignment_drag_changed", alignment_.translation_total);
        return true;
    }

    bool update_alignment_rotation_drag(int x, int y, WPARAM wparam) {
        if (!alignment_.rotation_drag_active) return false;
        int delta_x = x - alignment_.last_x;
        int delta_y = y - alignment_.last_y;
        alignment_.last_x = x;
        alignment_.last_y = y;
        if (delta_x == 0 && delta_y == 0) return true;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        float degrees_per_pixel = std::max(0.001f, alignment_.rotation_degrees_per_pixel);
        if (ctrl_down) degrees_per_pixel *= 4.0f;
        else if (shift_down && !alignment_.rotation_drag_roll) degrees_per_pixel *= 0.25f;
        DirectX::XMFLOAT3 delta(0.0f, 0.0f, 0.0f);
        if (alignment_.rotation_drag_roll) {
            delta.z = static_cast<float>(delta_x) * degrees_per_pixel;
        } else {
            delta.x = static_cast<float>(delta_y) * degrees_per_pixel;
            delta.y = static_cast<float>(delta_x) * degrees_per_pixel;
        }
        alignment_.rotation_total.x += delta.x;
        alignment_.rotation_total.y += delta.y;
        alignment_.rotation_total.z += delta.z;
        send_alignment_vector_event("alignment_rotation_changed", alignment_.rotation_total);
        return true;
    }

    bool update_alignment_drag(int x, int y, WPARAM wparam) {
        if (alignment_.rotation_drag_active) return update_alignment_rotation_drag(x, y, wparam);
        if (alignment_.drag_active) return update_alignment_translation_drag(x, y, wparam);
        return false;
    }

    void update_alignment_hover(int x, int y) {
        if (!alignment_.enabled || mesh_edit_.enabled || alignment_.drag_active || alignment_.rotation_drag_active) {
            return;
        }
        alignment_.hover_axis = alignment_axis_at(x, y);
    }

    bool finish_alignment_drag(int x, int y, WPARAM wparam) {
        if (alignment_.rotation_drag_active) {
            update_alignment_rotation_drag(x, y, wparam);
            send_alignment_vector_event("alignment_rotation_finished", alignment_.rotation_total);
            alignment_.rotation_drag_active = false;
            alignment_.rotation_drag_roll = false;
            alignment_.rotation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        if (alignment_.drag_active) {
            update_alignment_translation_drag(x, y, wparam);
            send_alignment_vector_event("alignment_drag_finished", alignment_.translation_total);
            alignment_.drag_active = false;
            alignment_.drag_axis.clear();
            alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        return false;
    }

    bool cancel_alignment_drag() {
        bool was_active = alignment_.drag_active || alignment_.rotation_drag_active;
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.rotation_drag_roll = false;
        alignment_.drag_axis.clear();
        alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        return was_active;
    }

    void draw_alignment_overlay_gdi() const {
        if (!alignment_.enabled || width_ <= 1 || height_ <= 1) return;
        auto points = alignment_axis_points();
        if (points.empty()) return;
        HDC dc = GetDC(hwnd_);
        if (!dc) return;
        int old_bk_mode = SetBkMode(dc, TRANSPARENT);
        COLORREF old_text_color = SetTextColor(dc, RGB(226, 232, 240));
        HPEN old_pen = reinterpret_cast<HPEN>(SelectObject(dc, GetStockObject(DC_PEN)));
        HBRUSH old_brush = reinterpret_cast<HBRUSH>(SelectObject(dc, GetStockObject(NULL_BRUSH)));
        const auto draw_axis = [&](const char* axis, COLORREF color, const ScreenPoint& start, const ScreenPoint& end) {
            bool active = alignment_.drag_axis == axis || alignment_.hover_axis == axis;
            SetDCPenColor(dc, color);
            SelectObject(dc, GetStockObject(DC_PEN));
            MoveToEx(dc, static_cast<int>(std::round(start.x)), static_cast<int>(std::round(start.y)), nullptr);
            LineTo(dc, static_cast<int>(std::round(end.x)), static_cast<int>(std::round(end.y)));
            int radius = active ? 8 : 6;
            Ellipse(
                dc,
                static_cast<int>(std::round(end.x)) - radius,
                static_cast<int>(std::round(end.y)) - radius,
                static_cast<int>(std::round(end.x)) + radius,
                static_cast<int>(std::round(end.y)) + radius);
            TextOutA(dc, static_cast<int>(std::round(end.x)) + 8, static_cast<int>(std::round(end.y)) - 8, axis, 1);
        };
        for (const auto& [axis, segment] : points) {
            COLORREF color = RGB(239, 68, 68);
            if (axis == "y") color = RGB(59, 130, 246);
            else if (axis == "z") color = RGB(34, 197, 94);
            draw_axis(axis.c_str(), color, segment.first, segment.second);
        }
        const ScreenPoint& origin = points.begin()->second.first;
        bool screen_active = alignment_.drag_axis == "screen" || alignment_.hover_axis == "screen";
        SetDCPenColor(dc, RGB(255, 244, 179));
        int radius = screen_active ? 10 : 8;
        Ellipse(
            dc,
            static_cast<int>(std::round(origin.x)) - radius,
            static_cast<int>(std::round(origin.y)) - radius,
            static_cast<int>(std::round(origin.x)) + radius,
            static_cast<int>(std::round(origin.y)) + radius);
        MoveToEx(dc, static_cast<int>(std::round(origin.x)) - radius + 3, static_cast<int>(std::round(origin.y)), nullptr);
        LineTo(dc, static_cast<int>(std::round(origin.x)) + radius - 3, static_cast<int>(std::round(origin.y)));
        MoveToEx(dc, static_cast<int>(std::round(origin.x)), static_cast<int>(std::round(origin.y)) - radius + 3, nullptr);
        LineTo(dc, static_cast<int>(std::round(origin.x)), static_cast<int>(std::round(origin.y)) + radius - 3);
        SelectObject(dc, old_pen);
        SelectObject(dc, old_brush);
        SetTextColor(dc, old_text_color);
        SetBkMode(dc, old_bk_mode);
        ReleaseDC(hwnd_, dc);
    }

    int source_part_at(int x, int y, float radius_pixels) const {
        int best_source_submesh = -1;
        float best_distance = radius_pixels;
        for (const PreviewBatch& batch : batches_) {
            if (batch.source_submesh_index < 0 || batch.cpu_positions.empty()) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                float screen_x = 0.0f;
                float screen_y = 0.0f;
                if (!project_position(position, screen_x, screen_y)) continue;
                float distance = std::hypot(static_cast<float>(x) - screen_x, static_cast<float>(y) - screen_y);
                if (distance < best_distance) {
                    best_distance = distance;
                    best_source_submesh = batch.source_submesh_index;
                }
            }
        }
        return best_source_submesh;
    }

    void send_source_part_event(const char* event_name, int source_submesh_index) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\""
            << ",\"source_submesh_index\":" << source_submesh_index
            << "}";
        send_json_event(out.str());
    }

    void update_source_part_hover(int x, int y) {
        if (mesh_edit_.enabled || alignment_.drag_active || alignment_.rotation_drag_active || drag_mode_ != 0) {
            return;
        }
        int source_submesh = source_part_at(x, y, 24.0f);
        if (source_submesh == source_part_.hovered_source_submesh) return;
        source_part_.hovered_source_submesh = source_submesh;
        send_source_part_event("source_part_hovered", source_submesh);
    }

    void begin_source_part_click(WPARAM wparam, int x, int y) {
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (mesh_edit_.enabled || alt_down || shift_down || ctrl_down) return;
        int source_submesh = source_part_at(x, y, 28.0f);
        if (source_submesh < 0) return;
        source_part_.click_pending = true;
        source_part_.click_source_submesh = source_submesh;
        source_part_.start_x = x;
        source_part_.start_y = y;
    }

    void finish_source_part_click(int x, int y) {
        if (!source_part_.click_pending) return;
        int source_submesh = source_part_.click_source_submesh;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (source_submesh < 0) return;
        if (std::hypot(static_cast<float>(x - source_part_.start_x), static_cast<float>(y - source_part_.start_y)) > 6.0f) {
            return;
        }
        send_source_part_event("source_part_selected", source_submesh);
    }

    float mesh_edit_falloff_weight(float distance_pixels, float radius_pixels) const {
        float normalized = std::clamp(distance_pixels / std::max(radius_pixels, 1e-6f), 0.0f, 1.0f);
        if (normalized >= 1.0f) return 0.0f;
        std::string mode = lower_copy(mesh_edit_.falloff);
        if (mode == "linear") return 1.0f - normalized;
        if (mode == "sharp") return (1.0f - normalized) * (1.0f - normalized);
        if (mode == "constant") return 1.0f;
        return 1.0f - (normalized * normalized * (3.0f - 2.0f * normalized));
    }

    std::vector<EditorCandidate> mesh_edit_candidates_at(int x, int y, float radius_pixels, bool nearest_only) const {
        std::vector<EditorCandidate> candidates;
        if (!mesh_edit_.enabled || width_ <= 0 || height_ <= 0) return candidates;
        for (const PreviewBatch& batch : batches_) {
            if (batch.cpu_positions.empty()) continue;
            for (size_t vertex_index = 0; vertex_index < batch.cpu_positions.size(); ++vertex_index) {
                int source_submesh = vertex_index < batch.cpu_source_submeshes.size()
                    ? batch.cpu_source_submeshes[vertex_index]
                    : batch.source_submesh_index;
                int source_vertex = vertex_index < batch.cpu_source_vertices.size()
                    ? batch.cpu_source_vertices[vertex_index]
                    : static_cast<int>(vertex_index);
                if (source_submesh < 0 || source_vertex < 0) continue;
                float screen_x = 0.0f;
                float screen_y = 0.0f;
                if (!project_position(batch.cpu_positions[vertex_index], screen_x, screen_y)) continue;
                float distance = std::hypot(static_cast<float>(x) - screen_x, static_cast<float>(y) - screen_y);
                if (distance > radius_pixels) continue;
                EditorCandidate candidate;
                candidate.batch_index = batch.index;
                candidate.source_submesh_index = source_submesh;
                candidate.source_vertex_index = source_vertex;
                candidate.position = batch.cpu_positions[vertex_index];
                candidate.screen_x = screen_x;
                candidate.screen_y = screen_y;
                candidate.distance = distance;
                candidate.weight = mesh_edit_falloff_weight(distance, radius_pixels);
                if (candidate.weight > 0.0f) candidates.push_back(candidate);
            }
        }
        std::sort(candidates.begin(), candidates.end(), [](const EditorCandidate& left, const EditorCandidate& right) {
            return left.distance < right.distance;
        });
        if (nearest_only && candidates.size() > 1) {
            candidates.resize(1);
        }
        constexpr size_t kMaxBrushCandidates = 6000;
        if (!nearest_only && candidates.size() > kMaxBrushCandidates) {
            candidates.resize(kMaxBrushCandidates);
        }
        return candidates;
    }

    std::vector<EditorCandidate> mesh_edit_selected_candidates() const {
        std::vector<EditorCandidate> candidates;
        if (mesh_edit_.selected_vertices.empty()) return candidates;
        std::set<std::pair<int, int>> seen;
        for (const PreviewBatch& batch : batches_) {
            for (size_t vertex_index = 0; vertex_index < batch.cpu_positions.size(); ++vertex_index) {
                int source_submesh = vertex_index < batch.cpu_source_submeshes.size()
                    ? batch.cpu_source_submeshes[vertex_index]
                    : batch.source_submesh_index;
                int source_vertex = vertex_index < batch.cpu_source_vertices.size()
                    ? batch.cpu_source_vertices[vertex_index]
                    : static_cast<int>(vertex_index);
                std::pair<int, int> key(source_submesh, source_vertex);
                if (mesh_edit_.selected_vertices.find(key) == mesh_edit_.selected_vertices.end() || seen.find(key) != seen.end()) {
                    continue;
                }
                seen.insert(key);
                EditorCandidate candidate;
                candidate.batch_index = batch.index;
                candidate.source_submesh_index = source_submesh;
                candidate.source_vertex_index = source_vertex;
                candidate.position = batch.cpu_positions[vertex_index];
                candidate.weight = 1.0f;
                candidates.push_back(candidate);
            }
        }
        return candidates;
    }

    DirectX::XMFLOAT3 mesh_edit_average_position(const std::vector<EditorCandidate>& candidates) const {
        if (candidates.empty()) return DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        DirectX::XMFLOAT3 total(0.0f, 0.0f, 0.0f);
        for (const EditorCandidate& candidate : candidates) {
            total.x += candidate.position.x;
            total.y += candidate.position.y;
            total.z += candidate.position.z;
        }
        float scale = 1.0f / static_cast<float>(candidates.size());
        return DirectX::XMFLOAT3(total.x * scale, total.y * scale, total.z * scale);
    }

    DirectX::XMFLOAT3 mesh_edit_drag_delta(int start_x, int start_y, int end_x, int end_y) const {
        float delta_x = static_cast<float>(end_x - start_x);
        float delta_y = static_cast<float>(end_y - start_y);
        float units_per_pixel = world_units_per_pixel();
        DirectX::XMMATRIX rotation = DirectX::XMMatrixRotationRollPitchYaw(
            DirectX::XMConvertToRadians(pitch_),
            DirectX::XMConvertToRadians(yaw_),
            0.0f);
        DirectX::XMVECTOR determinant{};
        DirectX::XMMATRIX inverse_rotation = DirectX::XMMatrixInverse(&determinant, rotation);
        DirectX::XMVECTOR right = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(1.0f, 0.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR up = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR horizontal = DirectX::XMVectorScale(right, delta_x * units_per_pixel);
        DirectX::XMVECTOR vertical = DirectX::XMVectorScale(up, delta_y * units_per_pixel);
        DirectX::XMVECTOR delta = DirectX::XMVectorSubtract(horizontal, vertical);
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, delta);
        return output;
    }

    std::string mesh_edit_groups_json(const std::vector<EditorCandidate>& candidates, bool full_weight) const {
        std::map<int, std::map<int, float>> grouped;
        for (const EditorCandidate& candidate : candidates) {
            if (candidate.source_submesh_index < 0 || candidate.source_vertex_index < 0) continue;
            float weight = full_weight ? 1.0f : std::clamp(candidate.weight, 0.0f, 1.0f);
            if (weight <= 0.0f) continue;
            float& slot = grouped[candidate.source_submesh_index][candidate.source_vertex_index];
            slot = std::max(slot, weight);
        }
        std::ostringstream out;
        out << "[";
        size_t group_index = 0;
        for (const auto& [source_submesh, weights] : grouped) {
            if (group_index++) out << ",";
            out << "{\"source_submesh_index\":" << source_submesh << ",\"source_vertex_indices\":[";
            size_t index = 0;
            for (const auto& [source_vertex, _weight] : weights) {
                if (index++) out << ",";
                out << source_vertex;
            }
            out << "],\"source_vertex_weights\":[";
            index = 0;
            for (const auto& [source_vertex, weight] : weights) {
                if (index++) out << ",";
                out << "[" << source_vertex << "," << weight << "]";
            }
            out << "]}";
        }
        out << "]";
        return out.str();
    }

    std::string mesh_edit_payload_json(
        const char* phase,
        const std::vector<EditorCandidate>& candidates,
        int x,
        int y,
        bool invert) const {
        bool drag_mode = mesh_edit_.tool == "grab" || mesh_edit_.tool == "vertex";
        DirectX::XMFLOAT3 center = mesh_edit_average_position(candidates);
        DirectX::XMFLOAT3 delta = mesh_edit_drag_delta(mesh_edit_.start_x, mesh_edit_.start_y, x, y);
        DirectX::XMFLOAT3 step_delta = mesh_edit_drag_delta(mesh_edit_.last_x, mesh_edit_.last_y, x, y);
        float radius_world = mesh_edit_.radius_pixels * world_units_per_pixel();
        float amount_world = drag_mode ? -static_cast<float>(y - mesh_edit_.start_y) * world_units_per_pixel() : radius_world * 0.08f;
        bool full_weight = mesh_edit_.target_mode == "vertex" || mesh_edit_.tool == "vertex";
        std::ostringstream out;
        out << "{\"stroke_id\":" << mesh_edit_.stroke_id
            << ",\"phase\":\"" << json_escape(phase ? phase : "") << "\""
            << ",\"mode\":\"" << (drag_mode ? "drag" : "brush") << "\""
            << ",\"tool\":\"" << json_escape(mesh_edit_.tool) << "\""
            << ",\"target_mode\":\"" << json_escape(mesh_edit_.target_mode) << "\""
            << ",\"selected_vertex_count\":" << mesh_edit_.selected_vertices.size()
            << ",\"center\":" << float3_json(center)
            << ",\"delta\":" << float3_delta_json(delta)
            << ",\"step_delta\":" << float3_delta_json(step_delta)
            << ",\"amount\":" << amount_world
            << ",\"radius\":" << radius_world
            << ",\"strength\":" << std::clamp(mesh_edit_.strength, 0.0f, 1.0f)
            << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\""
            << ",\"invert\":" << (invert ? "true" : "false")
            << ",\"groups\":" << mesh_edit_groups_json(candidates, full_weight)
            << "}";
        return out.str();
    }

    void send_mesh_edit_event(const char* event_name, const std::string& payload_json) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\",\"payload\":" << payload_json << "}";
        send_json_event(out.str());
    }

    void send_mesh_edit_selection_event() const {
        std::map<int, std::vector<int>> grouped;
        for (const auto& key : mesh_edit_.selected_vertices) {
            grouped[key.first].push_back(key.second);
        }
        std::ostringstream payload;
        payload << "{\"selected_vertex_count\":" << mesh_edit_.selected_vertices.size() << ",\"groups\":[";
        size_t group_index = 0;
        for (auto& [source_submesh, vertices] : grouped) {
            std::sort(vertices.begin(), vertices.end());
            if (group_index++) payload << ",";
            payload << "{\"source_submesh_index\":" << source_submesh << ",\"source_vertex_indices\":[";
            for (size_t index = 0; index < vertices.size(); ++index) {
                if (index) payload << ",";
                payload << vertices[index];
            }
            payload << "]}";
        }
        payload << "]}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

    bool begin_mesh_edit_drag(WPARAM wparam, int x, int y) {
        if (!mesh_edit_.enabled) return false;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        if (alt_down) return false;
        bool vertex_mode = mesh_edit_.target_mode == "vertex" || mesh_edit_.tool == "vertex";
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        std::vector<EditorCandidate> candidates = mesh_edit_candidates_at(
            x,
            y,
            vertex_mode ? 12.0f : mesh_edit_.radius_pixels,
            vertex_mode);
        if (vertex_mode && shift_down && !candidates.empty()) {
            std::pair<int, int> key(candidates[0].source_submesh_index, candidates[0].source_vertex_index);
            if (mesh_edit_.selected_vertices.find(key) == mesh_edit_.selected_vertices.end()) {
                mesh_edit_.selected_vertices.insert(key);
            } else {
                mesh_edit_.selected_vertices.erase(key);
            }
            send_mesh_edit_selection_event();
            return true;
        }
        if (vertex_mode && !candidates.empty()) {
            mesh_edit_.selected_vertices.clear();
            mesh_edit_.selected_vertices.insert(std::pair<int, int>(candidates[0].source_submesh_index, candidates[0].source_vertex_index));
            send_mesh_edit_selection_event();
        }
        std::vector<EditorCandidate> selected = mesh_edit_selected_candidates();
        if (vertex_mode && !selected.empty()) {
            candidates = std::move(selected);
        }
        if (candidates.empty()) return true;
        mesh_edit_.drag_active = true;
        mesh_edit_.previewed = false;
        mesh_edit_.stroke_id += 1;
        mesh_edit_.start_x = x;
        mesh_edit_.start_y = y;
        mesh_edit_.last_x = x;
        mesh_edit_.last_y = y;
        mesh_edit_.drag_candidates = candidates;
        SetCapture(hwnd_);
        send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json("start", candidates, x, y, false));
        return true;
    }

    bool update_mesh_edit_drag(int x, int y) {
        if (!mesh_edit_.drag_active) return false;
        bool drag_mode = mesh_edit_.tool == "grab" || mesh_edit_.tool == "vertex";
        std::vector<EditorCandidate> candidates = drag_mode
            ? mesh_edit_.drag_candidates
            : mesh_edit_candidates_at(x, y, mesh_edit_.radius_pixels, false);
        if (candidates.empty()) return true;
        bool ctrl_down = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json("preview", candidates, x, y, ctrl_down));
        mesh_edit_.last_x = x;
        mesh_edit_.last_y = y;
        mesh_edit_.previewed = true;
        return true;
    }

    bool finish_mesh_edit_drag(int x, int y) {
        if (!mesh_edit_.drag_active) return false;
        update_mesh_edit_drag(x, y);
        std::ostringstream payload;
        payload << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"phase\":\"finish\",\"tool\":\"" << json_escape(mesh_edit_.tool)
                << "\",\"previewed\":" << (mesh_edit_.previewed ? "true" : "false") << "}";
        send_mesh_edit_event("mesh_edit_stroke_finished", payload.str());
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_candidates.clear();
        mesh_edit_.previewed = false;
        if (GetCapture() == hwnd_) ReleaseCapture();
        return true;
    }

    bool cancel_mesh_edit_drag() {
        if (!mesh_edit_.drag_active) return false;
        std::ostringstream payload;
        payload << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"phase\":\"cancel\",\"tool\":\"" << json_escape(mesh_edit_.tool) << "\"}";
        send_mesh_edit_event("mesh_edit_stroke_cancelled", payload.str());
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_candidates.clear();
        mesh_edit_.previewed = false;
        if (GetCapture() == hwnd_) ReleaseCapture();
        return true;
    }

    void send_json_event(const std::string& payload) const {
        HWND parent = reinterpret_cast<HWND>(args_.parent_hwnd);
        if (!parent || !IsWindow(parent)) return;
        COPYDATASTRUCT cds{};
        cds.dwData = kCdmwEventCopyData;
        cds.cbData = static_cast<DWORD>(payload.size() + 1);
        cds.lpData = const_cast<char*>(payload.c_str());
        SendMessageW(parent, WM_COPYDATA, reinterpret_cast<WPARAM>(hwnd_), reinterpret_cast<LPARAM>(&cds));
    }

    void send_view_event(const char* reason) const {
        std::ostringstream out;
        out << "{\"event\":\"view_state\",\"reason\":\"" << json_escape(reason ? reason : "") << "\""
            << ",\"zoom_factor\":" << zoom_factor_
            << ",\"fit_to_view\":" << (fit_to_view_ ? "true" : "false")
            << ",\"yaw\":" << yaw_
            << ",\"pitch\":" << pitch_
            << ",\"pan\":[" << pan_x_ << "," << pan_y_ << "," << pan_z_ << "]"
            << "}";
        send_json_event(out.str());
    }

    bool handle_copy_data(const COPYDATASTRUCT* cds) {
        if (!cds || cds->dwData != kCdmwCommandCopyData || !cds->lpData || cds->cbData == 0) return false;
        const char* data = reinterpret_cast<const char*>(cds->lpData);
        size_t payload_size = static_cast<size_t>(cds->cbData);
        if (payload_size > 0 && data[payload_size - 1] == '\0') --payload_size;
        std::string payload(data, data + payload_size);
        std::string command = lower_copy(json_string_field(payload, "command"));
        if (command == "load_package") {
            pending_package_dir_ = utf8_to_wide(json_string_field(payload, "package_dir"));
            pending_status_file_ = utf8_to_wide(json_string_field(payload, "status_file"));
            pending_reset_view_ = json_bool_field(payload, "reset_view", false);
            cdmw_native_diag::event("command_load_package", {{"package_dir", cdmw_native_diag::path_to_utf8(fs::path(pending_package_dir_))}, {"status_file", cdmw_native_diag::path_to_utf8(fs::path(pending_status_file_))}});
            send_json_event("{\"event\":\"command_result\",\"command\":\"load_package\",\"ok\":true,\"queued\":true}");
            return true;
        }
        if (command == "clear_preview") {
            fs::path status_file = utf8_to_wide(json_string_field(payload, "status_file"));
            cdmw_native_diag::event("command_clear_preview", {{"status_file", cdmw_native_diag::path_to_utf8(status_file)}});
            clear_preview(status_file);
            send_json_event("{\"event\":\"command_result\",\"command\":\"clear_preview\",\"ok\":true}");
            return true;
        }
        if (command == "set_highlights") {
            std::set<int> highlighted;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                highlighted.insert(value);
            }
            int highlighted_batches = 0;
            for (PreviewBatch& batch : batches_) {
                bool active = highlighted.find(batch.source_submesh_index) != highlighted.end();
                batch.highlight_strength = active ? 0.34f : 0.0f;
                if (active) ++highlighted_batches;
            }
            std::ostringstream event;
            event << "{\"event\":\"highlight_state\",\"highlighted_batches\":" << highlighted_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_mesh_edit_state") {
            mesh_edit_.enabled = json_bool_field(payload, "enabled", mesh_edit_.enabled);
            mesh_edit_.target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            mesh_edit_.tool = lower_copy(json_string_field(payload, "tool", mesh_edit_.tool));
            mesh_edit_.falloff = lower_copy(json_string_field(payload, "falloff", mesh_edit_.falloff));
            mesh_edit_.radius_pixels = std::clamp(json_float_field(payload, "radius_pixels", mesh_edit_.radius_pixels), 2.0f, 512.0f);
            mesh_edit_.strength = std::clamp(json_float_field(payload, "strength", mesh_edit_.strength), 0.0f, 1.0f);
            mesh_edit_.show_vertices = json_bool_field(payload, "show_vertices", mesh_edit_.show_vertices);
            if (!mesh_edit_.enabled) {
                cancel_mesh_edit_drag();
            }
            send_json_event("{\"event\":\"mesh_edit_state\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_state") {
            alignment_.enabled = json_bool_field(payload, "enabled", alignment_.enabled);
            alignment_.translation_sensitivity = std::clamp(
                json_float_field(payload, "translation_sensitivity", alignment_.translation_sensitivity),
                0.05f,
                10.0f);
            alignment_.rotation_degrees_per_pixel = std::clamp(
                json_float_field(payload, "rotation_degrees_per_pixel", alignment_.rotation_degrees_per_pixel),
                0.001f,
                8.0f);
            alignment_.selected_source_submeshes.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) alignment_.selected_source_submeshes.insert(value);
            }
            if (!alignment_.enabled) {
                cancel_alignment_drag();
                alignment_.hover_axis.clear();
            }
            send_json_event("{\"event\":\"alignment_state\",\"ok\":true}");
            return true;
        }
        if (command == "clear_mesh_edit_selection") {
            mesh_edit_.selected_vertices.clear();
            send_mesh_edit_selection_event();
            return true;
        }
        if (command == "select_mesh_edit_brush") {
            std::vector<EditorCandidate> candidates = mesh_edit_candidates_at(
                last_mouse_x_,
                last_mouse_y_,
                mesh_edit_.radius_pixels,
                false);
            mesh_edit_.selected_vertices.clear();
            for (const EditorCandidate& candidate : candidates) {
                mesh_edit_.selected_vertices.insert(std::pair<int, int>(candidate.source_submesh_index, candidate.source_vertex_index));
            }
            send_mesh_edit_selection_event();
            return true;
        }
        if (command == "set_view") {
            yaw_ = json_float_field(payload, "yaw", yaw_);
            pitch_ = std::clamp(json_float_field(payload, "pitch", pitch_), -89.0f, 89.0f);
            zoom_factor_ = std::clamp(json_float_field(payload, "zoom_factor", zoom_factor_), 0.1f, 16.0f);
            fit_to_view_ = json_bool_field(payload, "fit_to_view", fit_to_view_);
            distance_ = fit_to_view_ ? kFitDistance : kFitDistance / std::max(zoom_factor_, 0.1f);
            send_view_event("set_view");
            return true;
        }
        send_json_event("{\"event\":\"warning\",\"message\":\"unknown D3D11 host command\"}");
        return false;
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
        send_view_event("reset");
    }

    void set_zoom_factor(float zoom_factor) {
        zoom_factor_ = std::clamp(zoom_factor, 0.1f, 16.0f);
        fit_to_view_ = false;
        distance_ = kFitDistance / zoom_factor_;
        send_view_event("zoom");
    }

    void set_fit_to_view(bool fit_to_view) {
        fit_to_view_ = fit_to_view;
        distance_ = fit_to_view_ ? kFitDistance : kFitDistance / std::max(zoom_factor_, 0.1f);
        send_view_event("fit");
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
        send_view_event("drag");
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
        send_view_event("wheel");
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
        sampler_desc.MaxAnisotropy = static_cast<UINT>(std::clamp(render_tuning_.max_anisotropy, 1, 16));
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
            batch.cpu_positions.clear();
            batch.cpu_source_submeshes.clear();
            batch.cpu_source_vertices.clear();
            batch.cpu_positions.reserve(static_cast<size_t>(batch.vertex_count));
            for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
                const float* values = reinterpret_cast<const float*>(data.data() + static_cast<size_t>(vertex_index) * kVertexStrideBytes);
                batch.cpu_positions.push_back(DirectX::XMFLOAT3(values[0], values[1], values[2]));
            }
            std::vector<uint8_t> identity_data = batch.identity_file.empty() ? std::vector<uint8_t>() : read_binary(batch.identity_file);
            if (identity_data.size() >= static_cast<size_t>(batch.vertex_count) * sizeof(int32_t) * 2u) {
                batch.cpu_source_submeshes.reserve(static_cast<size_t>(batch.vertex_count));
                batch.cpu_source_vertices.reserve(static_cast<size_t>(batch.vertex_count));
                const int32_t* identity = reinterpret_cast<const int32_t*>(identity_data.data());
                for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
                    batch.cpu_source_submeshes.push_back(static_cast<int>(identity[vertex_index * 2]));
                    batch.cpu_source_vertices.push_back(static_cast<int>(identity[vertex_index * 2 + 1]));
                }
            } else {
                batch.cpu_source_submeshes.assign(static_cast<size_t>(batch.vertex_count), batch.source_submesh_index);
                batch.cpu_source_vertices.reserve(static_cast<size_t>(batch.vertex_count));
                for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
                    batch.cpu_source_vertices.push_back(vertex_index);
                }
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
        cdmw_native_diag::event(
            "upload_batches",
            {
                {"batches", std::to_string(stats_.batch_count)},
                {"vertices", std::to_string(stats_.vertex_count)},
                {"geometry_ms", std::to_string(stats_.geometry_ms)},
                {"texture_ms", std::to_string(stats_.texture_ms)},
                {"dds_base", std::to_string(stats_.dds_uploaded.base)},
                {"dds_normal", std::to_string(stats_.dds_uploaded.normal)},
                {"dds_material", std::to_string(stats_.dds_uploaded.material)},
                {"dds_height", std::to_string(stats_.dds_uploaded.height)},
                {"png_fallback", std::to_string(stats_.png_fallback)},
                {"skipped", std::to_string(stats_.skipped.size())}
            });
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
            cdmw_native_diag::event("dds_upload_failed", {{"slot", slot_name}, {"path", wide_to_utf8(dds_path)}});
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
            cdmw_native_diag::event("png_fallback_failed", {{"slot", slot_name}, {"path", wide_to_utf8(png_fallback)}});
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
    RenderTuning render_tuning_;
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
    AlignmentState alignment_;
    SourcePartInteractionState source_part_;
    MeshEditState mesh_edit_;
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
    fs::path pending_package_dir_;
    fs::path pending_status_file_;
    bool pending_reset_view_ = false;
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
    cdmw_native_diag::event("startup", {{"backend", "D3D11"}, {"package_dir", cdmw_native_diag::path_to_utf8(args.preview_package)}, {"status_file", cdmw_native_diag::path_to_utf8(args.status_file)}});
    if (args.preview_package.empty() || !fs::is_directory(args.preview_package)) {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"preview package directory is missing\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "preview package directory is missing"}});
        return 2;
    }
    write_status(args.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"manifest\",\"message\":\"Loading native D3D11 preview package...\"}");
    std::string manifest = read_text(args.preview_package / L"manifest.json");
    RendererStats stats;
    std::vector<PreviewBatch> batches = parse_manifest_batches(args.preview_package, manifest, stats);
    ViewSettings view_settings = parse_view_settings(manifest);
    RenderTuning render_tuning = parse_render_tuning(manifest);
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
        cdmw_native_diag::event("startup_error", {{"reason", "failed to create preview window"}});
        return 3;
    }

    write_status(args.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"upload\",\"message\":\"Uploading D3D11 geometry and DDS textures...\"}");
    Renderer renderer(hwnd, args, std::move(batches), stats, view_settings, render_tuning);
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(&renderer));
    if (!renderer.initialize()) {
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 renderer initialization failed\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "renderer initialization failed"}});
        return 4;
    }
    write_status(args.status_file, loaded_payload(stats));
    cdmw_native_diag::event("loaded", {{"batches", std::to_string(stats.batch_count)}, {"vertices", std::to_string(stats.vertex_count)}});

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
            renderer.process_pending_commands();
            renderer.render();
        }
    }
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
    write_status(args.status_file, "{\"event\":\"closed\",\"backend\":\"D3D11\"}");
    cdmw_native_diag::event("clean_shutdown");
    return 0;
}

int wmain(int argc, wchar_t** argv) {
    Args args = parse_args(argc, argv);
    cdmw_native_diag::init("cdmw-d3d11-preview", args.crash_dir, args.diagnostic_log);
    if (args.self_test) {
        cdmw_native_diag::event("self_test_start");
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> context;
        D3D_FEATURE_LEVEL feature{};
        HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION, device.GetAddressOf(), &feature, context.GetAddressOf());
        if (FAILED(hr)) {
            cdmw_native_diag::event("self_test_error", {{"hresult", std::to_string(static_cast<unsigned int>(hr))}});
        } else {
            cdmw_native_diag::event("self_test_ok", {{"feature_level", std::to_string(static_cast<unsigned int>(feature))}});
        }
        std::cout << "{\"event\":\"self_test\",\"backend\":\"D3D11\",\"ok\":" << (SUCCEEDED(hr) ? "true" : "false") << "}\n";
        return SUCCEEDED(hr) ? 0 : 2;
    }
    if (args.backend != L"d3d11" && args.backend != L"D3D11") {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"only D3D11 backend is supported by this native host\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "unsupported backend"}, {"backend", cdmw_native_diag::wide_to_utf8_diag(args.backend)}});
        return 1;
    }
    return run_host(args);
}
