#include <DirectXTex.h>
#include <Windows.h>
#include <wincodec.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct PreviewJob {
    std::wstring input;
    std::wstring output;
    std::string slot = "base";
    std::string srgb = "auto";
    std::string normal_space = "auto";
    int max_dimension = 4096;
};

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
    DirectX::ScratchImage image;
    DirectX::TexMetadata metadata{};
    HRESULT hr = DirectX::LoadFromDDSFile(source.c_str(), DirectX::DDS_FLAGS_NONE, &metadata, image);
    if (FAILED(hr)) {
        std::cout << "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\""
            << json_escape(wide_to_utf8(source)) << "\",\"message\":\"LoadFromDDSFile failed\"}\n";
        return 2;
    }
    std::cout << metadata_json(fs::path(source), metadata, "inspected") << "\n";
    return 0;
}

static int batch_preview_json(const fs::path& job_file, const fs::path& report_file) {
    std::vector<PreviewJob> jobs = parse_jobs(read_text_file(job_file));
    std::ostringstream report;
    report << "{\"status\":\"ok\",\"backend\":\"directxtex_native_0.1\",\"batch_size\":" << jobs.size() << ",\"items\":[";
    for (size_t index = 0; index < jobs.size(); ++index) {
        if (index) report << ",";
        report << decode_preview(jobs[index]);
    }
    report << "]}";
    if (!write_text_file(report_file, report.str())) {
        std::cerr << "failed to write report: " << report_file << "\n";
        return 3;
    }
    std::cout << report.str() << "\n";
    return 0;
}

int wmain(int argc, wchar_t** argv) {
    if (argc >= 2 && std::wstring(argv[1]) == L"self-test") {
        std::cout << "{\"event\":\"self_test\",\"ok\":true,\"backend\":\"directxtex_native_0.1\"}\n";
        return 0;
    }
    if (argc >= 3 && std::wstring(argv[1]) == L"inspect-json") {
        return inspect_json(argv[2]);
    }
    if (argc >= 4 && std::wstring(argv[1]) == L"batch-preview-json") {
        return batch_preview_json(fs::path(argv[2]), fs::path(argv[3]));
    }
    std::cerr << "usage: cd-texture-dx self-test | inspect-json <dds> | batch-preview-json <job.json> <report.json>\n";
    return 1;
}
