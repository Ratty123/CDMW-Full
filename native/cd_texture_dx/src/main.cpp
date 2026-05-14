#include <DirectXTex.h>
#include <Windows.h>
#include <wincodec.h>

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

struct ComInitScope {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    bool needs_uninit = (hr == S_OK || hr == S_FALSE);

    ~ComInitScope() {
        if (needs_uninit) {
            CoUninitialize();
        }
    }
};

struct PreviewJob {
    std::wstring input;
    std::wstring output;
    std::string slot = "base";
    std::string srgb = "auto";
    std::string normal_space = "auto";
    int max_dimension = 4096;
};

struct EncodeJob {
    std::wstring input;
    std::wstring output;
    std::string format = "BC7_UNORM";
    std::string srgb = "auto";
    int width = 0;
    int height = 0;
    int mip_count = 1;
    bool overwrite = true;
};

struct CommonArgs {
    fs::path crash_dir;
    fs::path diagnostic_log;
};

static CommonArgs parse_common_args(int argc, wchar_t** argv) {
    CommonArgs args;
    for (int i = 1; i < argc; ++i) {
        std::wstring key = argv[i] ? argv[i] : L"";
        auto next = [&]() -> fs::path {
            if (i + 1 >= argc) return {};
            return fs::path(argv[++i]);
        };
        if (key == L"--crash-dir") args.crash_dir = next();
        else if (key == L"--diagnostic-log") args.diagnostic_log = next();
    }
    return args;
}

static std::wstring utf8_to_wide(const std::string& text) {
    if (text.empty()) return L"";
    int needed = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (needed <= 0) return L"";
    std::wstring output(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed);
    return output;
}

static std::string wide_to_utf8(const std::wstring& text) {
    if (text.empty()) return "";
    int needed = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return "";
    std::string output(static_cast<size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed, nullptr, nullptr);
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
        default:
            if (static_cast<unsigned char>(ch) < 0x20) out << "\\u00" << std::hex << int(static_cast<unsigned char>(ch));
            else out << ch;
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

static std::string read_text_file(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

static bool write_text_file(const fs::path& path, const std::string& text) {
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    std::ofstream stream(path, std::ios::binary);
    if (!stream) return false;
    stream.write(text.data(), static_cast<std::streamsize>(text.size()));
    return bool(stream);
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
    std::regex pattern("\"" + name + "\"\\s*:\\s*(true|false|1|0)", std::regex_constants::icase);
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    std::string value = match[1].str();
    std::transform(value.begin(), value.end(), value.begin(), ::tolower);
    return value == "true" || value == "1";
}

static std::vector<PreviewJob> parse_jobs(const std::string& text) {
    std::vector<PreviewJob> jobs;
    std::regex object_pattern("\\{[^{}]*\"(?:input|dds_path)\"[^{}]*\\}");
    auto begin = std::sregex_iterator(text.begin(), text.end(), object_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        std::string object = it->str();
        std::string input = json_string_field(object, "input", json_string_field(object, "dds_path"));
        std::string output = json_string_field(object, "output", json_string_field(object, "output_path"));
        if (input.empty() || output.empty()) continue;
        PreviewJob job;
        job.input = utf8_to_wide(input);
        job.output = utf8_to_wide(output);
        job.slot = json_string_field(object, "slot", json_string_field(object, "slot_kind", "base"));
        job.srgb = json_string_field(object, "srgb", "auto");
        job.normal_space = json_string_field(object, "normal_space", "auto");
        job.max_dimension = std::max(1, json_int_field(object, "max_dimension", json_int_field(object, "max_dim", 4096)));
        jobs.push_back(job);
    }
    return jobs;
}

static std::vector<EncodeJob> parse_encode_jobs(const std::string& text) {
    std::vector<EncodeJob> jobs;
    std::regex object_pattern("\\{[^{}]*\"(?:input|png_path|source_path)\"[^{}]*\\}");
    auto begin = std::sregex_iterator(text.begin(), text.end(), object_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        std::string object = it->str();
        std::string input = json_string_field(object, "input", json_string_field(object, "png_path", json_string_field(object, "source_path")));
        std::string output = json_string_field(object, "output", json_string_field(object, "dds_path", json_string_field(object, "output_path")));
        if (input.empty() || output.empty()) continue;
        EncodeJob job;
        job.input = utf8_to_wide(input);
        job.output = utf8_to_wide(output);
        job.format = json_string_field(object, "format", json_string_field(object, "texconv_format", "BC7_UNORM"));
        job.srgb = json_string_field(object, "srgb", "auto");
        job.width = std::max(0, json_int_field(object, "width", json_int_field(object, "target_width", 0)));
        job.height = std::max(0, json_int_field(object, "height", json_int_field(object, "target_height", 0)));
        job.mip_count = std::max(1, json_int_field(object, "mip_count", json_int_field(object, "mips", 1)));
        job.overwrite = json_bool_field(object, "overwrite", true);
        jobs.push_back(job);
    }
    return jobs;
}

static std::string upper_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::toupper(ch));
    });
    return value;
}

static DXGI_FORMAT dxgi_format_from_name(const std::string& raw_format) {
    std::string name = upper_copy(raw_format);
    if (name.rfind("DXGI_FORMAT_", 0) == 0) {
        name = name.substr(12);
    }
    static const std::unordered_map<std::string, DXGI_FORMAT> formats = {
        {"BC1_UNORM", DXGI_FORMAT_BC1_UNORM},
        {"BC1_UNORM_SRGB", DXGI_FORMAT_BC1_UNORM_SRGB},
        {"BC2_UNORM", DXGI_FORMAT_BC2_UNORM},
        {"BC2_UNORM_SRGB", DXGI_FORMAT_BC2_UNORM_SRGB},
        {"BC3_UNORM", DXGI_FORMAT_BC3_UNORM},
        {"BC3_UNORM_SRGB", DXGI_FORMAT_BC3_UNORM_SRGB},
        {"BC4_UNORM", DXGI_FORMAT_BC4_UNORM},
        {"BC4_SNORM", DXGI_FORMAT_BC4_SNORM},
        {"BC5_UNORM", DXGI_FORMAT_BC5_UNORM},
        {"BC5_SNORM", DXGI_FORMAT_BC5_SNORM},
        {"BC6H_UF16", DXGI_FORMAT_BC6H_UF16},
        {"BC6H_SF16", DXGI_FORMAT_BC6H_SF16},
        {"BC7_UNORM", DXGI_FORMAT_BC7_UNORM},
        {"BC7_UNORM_SRGB", DXGI_FORMAT_BC7_UNORM_SRGB},
        {"R8G8B8A8_UNORM", DXGI_FORMAT_R8G8B8A8_UNORM},
        {"R8G8B8A8_UNORM_SRGB", DXGI_FORMAT_R8G8B8A8_UNORM_SRGB},
        {"B8G8R8A8_UNORM", DXGI_FORMAT_B8G8R8A8_UNORM},
        {"B8G8R8A8_UNORM_SRGB", DXGI_FORMAT_B8G8R8A8_UNORM_SRGB},
        {"R16G16B16A16_FLOAT", DXGI_FORMAT_R16G16B16A16_FLOAT},
        {"R16G16B16A16_UNORM", DXGI_FORMAT_R16G16B16A16_UNORM},
        {"R16G16B16A16_SNORM", DXGI_FORMAT_R16G16B16A16_SNORM},
        {"R32G32B32A32_FLOAT", DXGI_FORMAT_R32G32B32A32_FLOAT},
    };
    auto it = formats.find(name);
    return it == formats.end() ? DXGI_FORMAT_UNKNOWN : it->second;
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
    case DXGI_FORMAT_B8G8R8A8_UNORM: return "DXGI_FORMAT_B8G8R8A8_UNORM";
    case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB: return "DXGI_FORMAT_B8G8R8A8_UNORM_SRGB";
    default: return "DXGI_FORMAT_" + std::to_string(static_cast<unsigned int>(format));
    }
}

static bool is_srgb_format(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_BC1_UNORM_SRGB:
    case DXGI_FORMAT_BC2_UNORM_SRGB:
    case DXGI_FORMAT_BC3_UNORM_SRGB:
    case DXGI_FORMAT_BC7_UNORM_SRGB:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
        return true;
    default:
        return false;
    }
}

static bool is_bc_compressed_format(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_BC1_TYPELESS:
    case DXGI_FORMAT_BC1_UNORM:
    case DXGI_FORMAT_BC1_UNORM_SRGB:
    case DXGI_FORMAT_BC2_TYPELESS:
    case DXGI_FORMAT_BC2_UNORM:
    case DXGI_FORMAT_BC2_UNORM_SRGB:
    case DXGI_FORMAT_BC3_TYPELESS:
    case DXGI_FORMAT_BC3_UNORM:
    case DXGI_FORMAT_BC3_UNORM_SRGB:
    case DXGI_FORMAT_BC4_TYPELESS:
    case DXGI_FORMAT_BC4_UNORM:
    case DXGI_FORMAT_BC4_SNORM:
    case DXGI_FORMAT_BC5_TYPELESS:
    case DXGI_FORMAT_BC5_UNORM:
    case DXGI_FORMAT_BC5_SNORM:
    case DXGI_FORMAT_BC6H_TYPELESS:
    case DXGI_FORMAT_BC6H_UF16:
    case DXGI_FORMAT_BC6H_SF16:
    case DXGI_FORMAT_BC7_TYPELESS:
    case DXGI_FORMAT_BC7_UNORM:
    case DXGI_FORMAT_BC7_UNORM_SRGB:
        return true;
    default:
        return false;
    }
}

static std::string bc_family(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_BC1_TYPELESS:
    case DXGI_FORMAT_BC1_UNORM:
    case DXGI_FORMAT_BC1_UNORM_SRGB:
        return "bc1";
    case DXGI_FORMAT_BC2_TYPELESS:
    case DXGI_FORMAT_BC2_UNORM:
    case DXGI_FORMAT_BC2_UNORM_SRGB:
        return "bc2";
    case DXGI_FORMAT_BC3_TYPELESS:
    case DXGI_FORMAT_BC3_UNORM:
    case DXGI_FORMAT_BC3_UNORM_SRGB:
        return "bc3";
    case DXGI_FORMAT_BC4_TYPELESS:
    case DXGI_FORMAT_BC4_UNORM:
    case DXGI_FORMAT_BC4_SNORM:
        return "bc4";
    case DXGI_FORMAT_BC5_TYPELESS:
    case DXGI_FORMAT_BC5_UNORM:
    case DXGI_FORMAT_BC5_SNORM:
        return "bc5";
    case DXGI_FORMAT_BC6H_TYPELESS:
    case DXGI_FORMAT_BC6H_UF16:
    case DXGI_FORMAT_BC6H_SF16:
        return "bc6h";
    case DXGI_FORMAT_BC7_TYPELESS:
    case DXGI_FORMAT_BC7_UNORM:
    case DXGI_FORMAT_BC7_UNORM_SRGB:
        return "bc7";
    default:
        return "";
    }
}

static std::string metadata_json(const fs::path& source, const DirectX::TexMetadata& metadata, const char* status) {
    const bool bc_compressed = is_bc_compressed_format(metadata.format);
    const std::string family = bc_family(metadata.format);
    std::ostringstream out;
    out << "{"
        << "\"status\":\"" << status << "\","
        << "\"backend\":\"directxtex_native_0.1\","
        << "\"native_backend\":\"directxtex\","
        << "\"source_path\":\"" << json_escape(wide_to_utf8(source.wstring())) << "\","
        << "\"format\":\"" << dxgi_format_name(metadata.format) << "\","
        << "\"dxgi_format\":" << static_cast<unsigned int>(metadata.format) << ","
        << "\"compressed\":" << (bc_compressed ? "true" : "false") << ","
        << "\"compressed_family\":\"" << json_escape(family) << "\","
        << "\"srgb\":" << (is_srgb_format(metadata.format) ? "true" : "false") << ","
        << "\"direct_upload_candidate\":" << (bc_compressed ? "true" : "false") << ","
        << "\"width\":" << metadata.width << ","
        << "\"height\":" << metadata.height << ","
        << "\"mip_count\":" << metadata.mipLevels << ","
        << "\"array_size\":" << metadata.arraySize << ","
        << "\"is_cubemap\":" << (metadata.IsCubemap() ? "true" : "false")
        << "}";
    return out.str();
}

static bool should_invert_green(const PreviewJob& job) {
    std::string slot = job.slot;
    std::string normal_space = job.normal_space;
    std::transform(slot.begin(), slot.end(), slot.begin(), ::tolower);
    std::transform(normal_space.begin(), normal_space.end(), normal_space.begin(), ::tolower);
    return slot == "normal" && (normal_space == "opengl" || normal_space == "qtquick" || normal_space == "auto");
}

static void invert_green_channel(DirectX::ScratchImage& image) {
    const DirectX::Image* frame = image.GetImage(0, 0, 0);
    if (!frame || frame->format != DXGI_FORMAT_R8G8B8A8_UNORM) return;
    for (size_t y = 0; y < frame->height; ++y) {
        uint8_t* row = frame->pixels + (frame->rowPitch * y);
        for (size_t x = 0; x < frame->width; ++x) {
            uint8_t* pixel = row + (x * 4);
            pixel[1] = static_cast<uint8_t>(255 - pixel[1]);
        }
    }
}

static std::string decode_preview(const PreviewJob& job) {
    auto started = std::chrono::steady_clock::now();
    DirectX::ScratchImage source_image;
    DirectX::TexMetadata metadata{};
    HRESULT hr = DirectX::LoadFromDDSFile(job.input.c_str(), DirectX::DDS_FLAGS_NONE, &metadata, source_image);
    if (FAILED(hr)) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"LoadFromDDSFile failed: 0x" +
            std::to_string(static_cast<unsigned int>(hr)) + "\"}";
    }
    const DirectX::Image* first = source_image.GetImage(0, 0, 0);
    if (!first) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"DDS has no first image\"}";
    }

    DirectX::ScratchImage rgba;
    hr = DirectX::Convert(*first, DXGI_FORMAT_R8G8B8A8_UNORM, DirectX::TEX_FILTER_DEFAULT, DirectX::TEX_THRESHOLD_DEFAULT, rgba);
    if (FAILED(hr)) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"Convert RGBA8 failed: 0x" +
            std::to_string(static_cast<unsigned int>(hr)) + "\"}";
    }

    DirectX::ScratchImage* output_image = &rgba;
    DirectX::ScratchImage resized;
    const DirectX::Image* rgba_image = rgba.GetImage(0, 0, 0);
    size_t target_width = rgba_image ? rgba_image->width : 0;
    size_t target_height = rgba_image ? rgba_image->height : 0;
    if (rgba_image && job.max_dimension > 0) {
        size_t longest = std::max(rgba_image->width, rgba_image->height);
        if (longest > static_cast<size_t>(job.max_dimension)) {
            double scale = static_cast<double>(job.max_dimension) / static_cast<double>(longest);
            target_width = std::max<size_t>(1, static_cast<size_t>(std::llround(rgba_image->width * scale)));
            target_height = std::max<size_t>(1, static_cast<size_t>(std::llround(rgba_image->height * scale)));
            hr = DirectX::Resize(*rgba_image, target_width, target_height, DirectX::TEX_FILTER_DEFAULT, resized);
            if (SUCCEEDED(hr)) output_image = &resized;
        }
    }
    if (should_invert_green(job)) {
        invert_green_channel(*output_image);
    }

    std::error_code ec;
    fs::create_directories(fs::path(job.output).parent_path(), ec);
    const DirectX::Image* final_image = output_image->GetImage(0, 0, 0);
    hr = DirectX::SaveToWICFile(*final_image, DirectX::WIC_FLAGS_NONE, GUID_ContainerFormatPng, job.output.c_str());
    auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    if (FAILED(hr)) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"SaveToWICFile failed: 0x" +
            std::to_string(static_cast<unsigned int>(hr)) + "\"}";
    }
    std::ostringstream out;
    const bool bc_compressed = is_bc_compressed_format(metadata.format);
    const std::string family = bc_family(metadata.format);
    const bool normal_green_inverted = should_invert_green(job);
    out << "{"
        << "\"status\":\"decoded\","
        << "\"backend\":\"directxtex_native_0.1\","
        << "\"native_backend\":\"directxtex\","
        << "\"source_path\":\"" << json_escape(wide_to_utf8(job.input)) << "\","
        << "\"output_path\":\"" << json_escape(wide_to_utf8(job.output)) << "\","
        << "\"slot\":\"" << json_escape(job.slot) << "\","
        << "\"format\":\"" << dxgi_format_name(metadata.format) << "\","
        << "\"dxgi_format\":" << static_cast<unsigned int>(metadata.format) << ","
        << "\"compressed\":" << (bc_compressed ? "true" : "false") << ","
        << "\"compressed_family\":\"" << json_escape(family) << "\","
        << "\"srgb\":" << (is_srgb_format(metadata.format) ? "true" : "false") << ","
        << "\"direct_upload_candidate\":" << (bc_compressed ? "true" : "false") << ","
        << "\"width\":" << metadata.width << ","
        << "\"height\":" << metadata.height << ","
        << "\"prepared_width\":" << target_width << ","
        << "\"prepared_height\":" << target_height << ","
        << "\"mip_count\":" << metadata.mipLevels << ","
        << "\"normal_space\":\"" << (normal_green_inverted ? "opengl_green_inverted" : job.normal_space) << "\","
        << "\"normal_green_inverted\":" << (normal_green_inverted ? "true" : "false") << ","
        << "\"decode_ms\":" << elapsed
        << "}";
    return out.str();
}

static int inspect_json(const std::wstring& source) {
    cdmw_native_diag::event("inspect_start", {{"source_path", wide_to_utf8(source)}});
    DirectX::ScratchImage image;
    DirectX::TexMetadata metadata{};
    HRESULT hr = DirectX::LoadFromDDSFile(source.c_str(), DirectX::DDS_FLAGS_NONE, &metadata, image);
    if (FAILED(hr)) {
        cdmw_native_diag::event("inspect_error", {{"source_path", wide_to_utf8(source)}, {"hresult", std::to_string(static_cast<unsigned int>(hr))}});
        std::cout << "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\""
            << json_escape(wide_to_utf8(source)) << "\",\"message\":\"LoadFromDDSFile failed\"}\n";
        return 2;
    }
    cdmw_native_diag::event("inspect_ok", {{"source_path", wide_to_utf8(source)}, {"format", dxgi_format_name(metadata.format)}, {"width", std::to_string(metadata.width)}, {"height", std::to_string(metadata.height)}});
    std::cout << metadata_json(fs::path(source), metadata, "inspected") << "\n";
    return 0;
}

static int batch_preview_json(const fs::path& job_file, const fs::path& report_file) {
    std::vector<PreviewJob> jobs = parse_jobs(read_text_file(job_file));
    cdmw_native_diag::event("batch_preview_start", {{"job_file", cdmw_native_diag::path_to_utf8(job_file)}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}, {"batch_size", std::to_string(jobs.size())}});
    std::ostringstream report;
    report << "{\"status\":\"ok\",\"backend\":\"directxtex_native_0.1\",\"batch_size\":" << jobs.size() << ",\"items\":[";
    size_t errors = 0;
    for (size_t index = 0; index < jobs.size(); ++index) {
        if (index) report << ",";
        const std::string item = decode_preview(jobs[index]);
        if (item.find("\"status\":\"error\"") != std::string::npos) ++errors;
        report << item;
    }
    report << "]}";
    if (!write_text_file(report_file, report.str())) {
        std::cerr << "failed to write report: " << report_file << "\n";
        cdmw_native_diag::event("batch_preview_error", {{"reason", "failed to write report"}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}});
        return 3;
    }
    cdmw_native_diag::event("batch_preview_complete", {{"batch_size", std::to_string(jobs.size())}, {"errors", std::to_string(errors)}});
    std::cout << report.str() << "\n";
    return 0;
}

static std::string encode_dds(const EncodeJob& job) {
    auto started = std::chrono::steady_clock::now();
    if (!job.overwrite && fs::exists(fs::path(job.output))) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
            "\",\"message\":\"output exists and overwrite=false\"}";
    }
    DXGI_FORMAT target_format = dxgi_format_from_name(job.format);
    if (target_format == DXGI_FORMAT_UNKNOWN) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
            "\",\"message\":\"unsupported DDS format " + json_escape(job.format) + "\"}";
    }

    DirectX::ScratchImage source_image;
    DirectX::TexMetadata source_metadata{};
    HRESULT hr = DirectX::LoadFromWICFile(job.input.c_str(), DirectX::WIC_FLAGS_NONE, &source_metadata, source_image);
    if (FAILED(hr)) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
            "\",\"message\":\"LoadFromWICFile failed: 0x" + std::to_string(static_cast<unsigned int>(hr)) + "\"}";
    }
    const DirectX::Image* image = source_image.GetImage(0, 0, 0);
    if (!image) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
            "\",\"message\":\"input image has no first frame\"}";
    }

    DirectX::ScratchImage converted;
    DirectX::ScratchImage* working = &source_image;
    DXGI_FORMAT intermediate_format = DirectX::IsCompressed(target_format)
        ? DXGI_FORMAT_R8G8B8A8_UNORM
        : target_format;
    if (image->format != intermediate_format) {
        hr = DirectX::Convert(*image, intermediate_format, DirectX::TEX_FILTER_DEFAULT, DirectX::TEX_THRESHOLD_DEFAULT, converted);
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
                "\",\"message\":\"Convert failed: 0x" + std::to_string(static_cast<unsigned int>(hr)) + "\"}";
        }
        working = &converted;
        image = working->GetImage(0, 0, 0);
    }

    DirectX::ScratchImage resized;
    const size_t target_width = job.width > 0 ? static_cast<size_t>(job.width) : image->width;
    const size_t target_height = job.height > 0 ? static_cast<size_t>(job.height) : image->height;
    if (target_width != image->width || target_height != image->height) {
        hr = DirectX::Resize(*image, target_width, target_height, DirectX::TEX_FILTER_DEFAULT, resized);
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
                "\",\"message\":\"Resize failed: 0x" + std::to_string(static_cast<unsigned int>(hr)) + "\"}";
        }
        working = &resized;
        image = working->GetImage(0, 0, 0);
    }

    DirectX::ScratchImage mip_chain;
    if (job.mip_count > 1) {
        hr = DirectX::GenerateMipMaps(
            *image,
            DirectX::TEX_FILTER_DEFAULT,
            static_cast<size_t>(job.mip_count),
            mip_chain
        );
        if (SUCCEEDED(hr)) {
            working = &mip_chain;
        }
    }

    DirectX::ScratchImage compressed_or_final;
    DirectX::ScratchImage* final_image = working;
    if (DirectX::IsCompressed(target_format)) {
        hr = DirectX::Compress(
            working->GetImages(),
            working->GetImageCount(),
            working->GetMetadata(),
            target_format,
            DirectX::TEX_COMPRESS_DEFAULT,
            DirectX::TEX_THRESHOLD_DEFAULT,
            compressed_or_final
        );
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
                "\",\"message\":\"Compress failed: 0x" + std::to_string(static_cast<unsigned int>(hr)) + "\"}";
        }
        final_image = &compressed_or_final;
    } else if (working->GetMetadata().format != target_format) {
        hr = DirectX::Convert(
            working->GetImages(),
            working->GetImageCount(),
            working->GetMetadata(),
            target_format,
            DirectX::TEX_FILTER_DEFAULT,
            DirectX::TEX_THRESHOLD_DEFAULT,
            compressed_or_final
        );
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
                "\",\"message\":\"Final Convert failed: 0x" + std::to_string(static_cast<unsigned int>(hr)) + "\"}";
        }
        final_image = &compressed_or_final;
    }

    std::error_code ec;
    fs::create_directories(fs::path(job.output).parent_path(), ec);
    hr = DirectX::SaveToDDSFile(
        final_image->GetImages(),
        final_image->GetImageCount(),
        final_image->GetMetadata(),
        DirectX::DDS_FLAGS_NONE,
        job.output.c_str()
    );
    const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
    if (FAILED(hr)) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" + json_escape(wide_to_utf8(job.output)) +
            "\",\"message\":\"SaveToDDSFile failed: 0x" + std::to_string(static_cast<unsigned int>(hr)) + "\"}";
    }
    const DirectX::TexMetadata metadata = final_image->GetMetadata();
    std::ostringstream out;
    out << "{"
        << "\"status\":\"encoded\","
        << "\"backend\":\"directxtex_native_0.1\","
        << "\"native_backend\":\"directxtex\","
        << "\"source_path\":\"" << json_escape(wide_to_utf8(job.input)) << "\","
        << "\"output_path\":\"" << json_escape(wide_to_utf8(job.output)) << "\","
        << "\"format\":\"" << dxgi_format_name(metadata.format) << "\","
        << "\"requested_format\":\"" << json_escape(job.format) << "\","
        << "\"dxgi_format\":" << static_cast<unsigned int>(metadata.format) << ","
        << "\"compressed\":" << (DirectX::IsCompressed(metadata.format) ? "true" : "false") << ","
        << "\"compressed_family\":\"" << json_escape(bc_family(metadata.format)) << "\","
        << "\"srgb\":" << (is_srgb_format(metadata.format) ? "true" : "false") << ","
        << "\"width\":" << metadata.width << ","
        << "\"height\":" << metadata.height << ","
        << "\"mip_count\":" << metadata.mipLevels << ","
        << "\"encode_ms\":" << elapsed
        << "}";
    return out.str();
}

static int batch_encode_json(const fs::path& job_file, const fs::path& report_file) {
    std::vector<EncodeJob> jobs = parse_encode_jobs(read_text_file(job_file));
    cdmw_native_diag::event("batch_encode_start", {{"job_file", cdmw_native_diag::path_to_utf8(job_file)}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}, {"batch_size", std::to_string(jobs.size())}});
    std::ostringstream report;
    report << "{\"status\":\"ok\",\"backend\":\"directxtex_native_0.1\",\"batch_size\":" << jobs.size() << ",\"items\":[";
    bool any_error = false;
    for (size_t index = 0; index < jobs.size(); ++index) {
        if (index) report << ",";
        const std::string item = encode_dds(jobs[index]);
        if (item.find("\"status\":\"error\"") != std::string::npos) any_error = true;
        report << item;
    }
    report << "]}";
    if (!write_text_file(report_file, report.str())) {
        std::cerr << "failed to write report: " << report_file << "\n";
        cdmw_native_diag::event("batch_encode_error", {{"reason", "failed to write report"}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}});
        return 3;
    }
    cdmw_native_diag::event("batch_encode_complete", {{"batch_size", std::to_string(jobs.size())}, {"any_error", any_error ? "true" : "false"}});
    std::cout << report.str() << "\n";
    return any_error ? 2 : 0;
}

int wmain(int argc, wchar_t** argv) {
    CommonArgs common_args = parse_common_args(argc, argv);
    cdmw_native_diag::init("cd-texture-dx", common_args.crash_dir, common_args.diagnostic_log);
    ComInitScope com_init;
    if (argc >= 2 && std::wstring(argv[1]) == L"self-test") {
        cdmw_native_diag::event("self_test_ok");
        std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"directxtex_native_0.1\"}\n";
        return 0;
    }
    if (argc >= 3 && std::wstring(argv[1]) == L"inspect-json") {
        return inspect_json(argv[2]);
    }
    if (argc >= 4 && std::wstring(argv[1]) == L"batch-preview-json") {
        return batch_preview_json(fs::path(argv[2]), fs::path(argv[3]));
    }
    if (argc >= 4 && std::wstring(argv[1]) == L"batch-encode-json") {
        return batch_encode_json(fs::path(argv[2]), fs::path(argv[3]));
    }
    std::cerr << "usage: cd-texture-dx self-test | inspect-json <dds> | batch-preview-json <job.json> <report.json> | batch-encode-json <job.json> <report.json>\n";
    return 1;
}
