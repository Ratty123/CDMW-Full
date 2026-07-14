#include "texture_tool_internal.h"

#include <DirectXTex.h>
#include <Windows.h>
#include <wincodec.h>

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

CommonArgs parse_common_args(int argc, wchar_t** argv) {
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

std::wstring utf8_to_wide(const std::string& text) {
    if (text.empty()) return L"";
    int needed = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (needed <= 0) return L"";
    std::wstring output(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed);
    return output;
}

std::string wide_to_utf8(const std::wstring& text) {
    if (text.empty()) return "";
    int needed = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return "";
    std::string output(static_cast<size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed, nullptr, nullptr);
    return output;
}

std::string json_escape(const std::string& text) {
    std::ostringstream out;
    const char* hex = "0123456789abcdef";
    for (unsigned char raw : text) {
        const char ch = static_cast<char>(raw);
        switch (ch) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\b': out << "\\b"; break;
        case '\f': out << "\\f"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (raw < 0x20) {
                out << "\\u00" << hex[(raw >> 4) & 0xF] << hex[raw & 0xF];
            } else {
                out << ch;
            }
        }
    }
    return out.str();
}

std::string exception_item_json(
    const std::wstring& source,
    const std::wstring& output,
    const char* operation,
    const char* message
) {
    std::ostringstream out;
    out << "{"
        << "\"status\":\"error\","
        << "\"backend\":\"directxtex_native_0.1\","
        << "\"source_path\":\"" << json_escape(wide_to_utf8(source)) << "\","
        << "\"output_path\":\"" << json_escape(wide_to_utf8(output)) << "\","
        << "\"operation\":\"" << json_escape(operation ? operation : "") << "\","
        << "\"exception_type\":\"cxx_exception\","
        << "\"message\":\"" << json_escape(message ? message : "native C++ exception") << "\""
        << "}";
    return out.str();
}

void record_caught_exception(const char* event_name, const char* operation, const char* message) noexcept {
    const char* safe_event = event_name ? event_name : "native_cxx_exception";
    const char* safe_operation = operation ? operation : "unknown";
    const char* safe_message = message ? message : "native C++ exception";
    try {
        cdmw_native_diag::event(
            safe_event,
            {{"operation", safe_operation}, {"message", safe_message}}
        );
    } catch (...) {
        // Diagnostics must never turn a recovered native exception into a crash.
    }
    std::fprintf(stderr, "%s failed with a C++ exception: %s\n", safe_operation, safe_message);
}

static int json_hex_value(char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

static bool parse_json_hex4(const std::string& text, size_t offset, uint32_t& value) {
    if (offset + 4 > text.size()) return false;
    uint32_t parsed = 0;
    for (size_t index = 0; index < 4; ++index) {
        const int digit = json_hex_value(text[offset + index]);
        if (digit < 0) return false;
        parsed = (parsed << 4) | static_cast<uint32_t>(digit);
    }
    value = parsed;
    return true;
}

static void append_utf8_codepoint(std::string& output, uint32_t codepoint) {
    if (codepoint <= 0x7F) {
        output.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7FF) {
        output.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else if (codepoint <= 0xFFFF) {
        output.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
        output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else if (codepoint <= 0x10FFFF) {
        output.push_back(static_cast<char>(0xF0 | (codepoint >> 18)));
        output.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F)));
        output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else {
        append_utf8_codepoint(output, 0xFFFD);
    }
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
        case '/': out.push_back('/'); break;
        case 'b': out.push_back('\b'); break;
        case 'f': out.push_back('\f'); break;
        case 'n': out.push_back('\n'); break;
        case 'r': out.push_back('\r'); break;
        case 't': out.push_back('\t'); break;
        case 'u': {
            uint32_t codepoint = 0;
            if (!parse_json_hex4(text, i + 1, codepoint)) {
                append_utf8_codepoint(out, 0xFFFD);
                break;
            }
            i += 4;
            if (codepoint >= 0xD800 && codepoint <= 0xDBFF && i + 6 < text.size() &&
                text[i + 1] == '\\' && text[i + 2] == 'u') {
                uint32_t low = 0;
                if (parse_json_hex4(text, i + 3, low) && low >= 0xDC00 && low <= 0xDFFF) {
                    codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00);
                    i += 6;
                }
            }
            if (codepoint >= 0xD800 && codepoint <= 0xDFFF) codepoint = 0xFFFD;
            append_utf8_codepoint(out, codepoint);
            break;
        }
        default: out.push_back(next); break;
        }
    }
    return out;
}

std::string read_text_file(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

bool write_text_file(const fs::path& path, const std::string& text) {
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    std::ofstream stream(path, std::ios::binary);
    if (!stream) return false;
    stream.write(text.data(), static_cast<std::streamsize>(text.size()));
    return bool(stream);
}

static size_t skip_json_space(const std::string& text, size_t offset) {
    while (offset < text.size()) {
        const char ch = text[offset];
        if (ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n') break;
        ++offset;
    }
    return offset;
}

static bool json_string_token(const std::string& text, size_t offset, size_t& end, std::string& value) {
    if (offset >= text.size() || text[offset] != '"') return false;
    bool escaped = false;
    for (size_t index = offset + 1; index < text.size(); ++index) {
        const char ch = text[index];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (ch == '\\') {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            value = json_unescape(text.substr(offset + 1, index - offset - 1));
            end = index + 1;
            return true;
        }
    }
    return false;
}

static bool json_field_value_offset(const std::string& object, const std::string& name, size_t& value_offset) {
    for (size_t index = 0; index < object.size();) {
        if (object[index] != '"') {
            ++index;
            continue;
        }
        size_t token_end = index;
        std::string token;
        if (!json_string_token(object, index, token_end, token)) return false;
        size_t separator = skip_json_space(object, token_end);
        if (token == name && separator < object.size() && object[separator] == ':') {
            value_offset = skip_json_space(object, separator + 1);
            return true;
        }
        index = token_end;
    }
    return false;
}

static std::string json_string_field(const std::string& object, const std::string& name, const std::string& fallback = "") {
    size_t value_offset = 0;
    if (!json_field_value_offset(object, name, value_offset)) return fallback;
    size_t token_end = value_offset;
    std::string value;
    return json_string_token(object, value_offset, token_end, value) ? value : fallback;
}

static int json_int_field(const std::string& object, const std::string& name, int fallback = 0) {
    size_t value_offset = 0;
    if (!json_field_value_offset(object, name, value_offset)) return fallback;
    size_t end = value_offset;
    if (end < object.size() && object[end] == '-') ++end;
    while (end < object.size() && object[end] >= '0' && object[end] <= '9') ++end;
    if (end == value_offset || (end == value_offset + 1 && object[value_offset] == '-')) return fallback;
    try {
        return std::stoi(object.substr(value_offset, end - value_offset));
    } catch (...) {
        return fallback;
    }
}

static bool json_bool_field(const std::string& object, const std::string& name, bool fallback = false) {
    size_t value_offset = 0;
    if (!json_field_value_offset(object, name, value_offset)) return fallback;
    if (object.compare(value_offset, 4, "true") == 0 || object.compare(value_offset, 1, "1") == 0) return true;
    if (object.compare(value_offset, 5, "false") == 0 || object.compare(value_offset, 1, "0") == 0) return false;
    return fallback;
}

static std::vector<std::string> json_leaf_objects(const std::string& text) {
    struct Frame {
        size_t start = 0;
        bool has_child = false;
    };
    std::vector<Frame> frames;
    std::vector<std::string> objects;
    bool in_string = false;
    bool escaped = false;
    for (size_t index = 0; index < text.size(); ++index) {
        const char ch = text[index];
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
            if (!frames.empty()) frames.back().has_child = true;
            frames.push_back({index, false});
        } else if (ch == '}' && !frames.empty()) {
            const Frame frame = frames.back();
            frames.pop_back();
            if (!frame.has_child) objects.push_back(text.substr(frame.start, index - frame.start + 1));
        }
    }
    return objects;
}

std::vector<PreviewJob> parse_jobs(const std::string& text) {
    std::vector<PreviewJob> jobs;
    for (const std::string& object : json_leaf_objects(text)) {
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

std::vector<EncodeJob> parse_encode_jobs(const std::string& text) {
    std::vector<EncodeJob> jobs;
    for (const std::string& object : json_leaf_objects(text)) {
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

bool json_parser_self_test() {
    const std::string preview_json = R"json({
        "version": 1,
        "backend": "directxtex_native_0.1",
        "jobs": [
            {
                "input": "C:\\textures\\caf\u00e9{base}.dds",
                "output": "C:\\out\\preview.png",
                "slot": "base",
                "max_dimension": 512
            },
            {
                "dds_path": "D:\\emoji\\blade\ud83d\udde1.dds",
                "output_path": "D:\\out\\second.png",
                "slot_kind": "normal",
                "max_dim": 128
            }
        ]
    })json";
    const std::vector<PreviewJob> previews = parse_jobs(preview_json);
    const std::string expected_first = std::string("C:\\textures\\caf") + "\xC3\xA9" + "{base}.dds";
    const std::string expected_second = std::string("D:\\emoji\\blade") + "\xF0\x9F\x97\xA1" + ".dds";
    if (previews.size() != 2 ||
        wide_to_utf8(previews[0].input) != expected_first ||
        wide_to_utf8(previews[0].output) != "C:\\out\\preview.png" ||
        previews[0].slot != "base" ||
        previews[0].max_dimension != 512 ||
        wide_to_utf8(previews[1].input) != expected_second ||
        wide_to_utf8(previews[1].output) != "D:\\out\\second.png" ||
        previews[1].slot != "normal" ||
        previews[1].max_dimension != 128) {
        return false;
    }

    const std::string encode_json = R"json({
        "jobs": [
            {
                "png_path": "C:\\source\\a\"b.png",
                "dds_path": "C:\\output\\a.dds",
                "format": "BC7_UNORM",
                "mips": 4,
                "overwrite": false
            }
        ]
    })json";
    const std::vector<EncodeJob> encodes = parse_encode_jobs(encode_json);
    return encodes.size() == 1 &&
        wide_to_utf8(encodes[0].input) == "C:\\source\\a\"b.png" &&
        wide_to_utf8(encodes[0].output) == "C:\\output\\a.dds" &&
        encodes[0].format == "BC7_UNORM" &&
        encodes[0].mip_count == 4 &&
        !encodes[0].overwrite;
}

static std::string upper_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::toupper(ch));
    });
    return value;
}

DXGI_FORMAT dxgi_format_from_name(const std::string& raw_format) {
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
        {"R8_UNORM", DXGI_FORMAT_R8_UNORM},
        {"R16_UNORM", DXGI_FORMAT_R16_UNORM},
        {"R16G16B16A16_FLOAT", DXGI_FORMAT_R16G16B16A16_FLOAT},
        {"R16G16B16A16_UNORM", DXGI_FORMAT_R16G16B16A16_UNORM},
        {"R16G16B16A16_SNORM", DXGI_FORMAT_R16G16B16A16_SNORM},
        {"R32G32B32A32_FLOAT", DXGI_FORMAT_R32G32B32A32_FLOAT},
    };
    auto it = formats.find(name);
    return it == formats.end() ? DXGI_FORMAT_UNKNOWN : it->second;
}

std::string dxgi_format_name(DXGI_FORMAT format) {
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
    case DXGI_FORMAT_R8_UNORM: return "DXGI_FORMAT_R8_UNORM";
    case DXGI_FORMAT_R16_UNORM: return "DXGI_FORMAT_R16_UNORM";
    default: return "DXGI_FORMAT_" + std::to_string(static_cast<unsigned int>(format));
    }
}

bool is_srgb_format(DXGI_FORMAT format) {
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

bool is_bc_compressed_format(DXGI_FORMAT format) {
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

std::string bc_family(DXGI_FORMAT format) {
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

std::string metadata_json(const fs::path& source, const DirectX::TexMetadata& metadata, const char* status) {
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

int write_batch_exception_report(
    const fs::path& report_file,
    const char* operation,
    const char* message
) {
    std::ostringstream report;
    report << "{"
        << "\"status\":\"error\","
        << "\"backend\":\"directxtex_native_0.1\","
        << "\"batch_size\":0,"
        << "\"items\":[],"
        << "\"operation\":\"" << json_escape(operation ? operation : "") << "\","
        << "\"exception_type\":\"cxx_exception\","
        << "\"message\":\"" << json_escape(message ? message : "native C++ exception") << "\""
        << "}";
    if (!write_text_file(report_file, report.str())) {
        return 3;
    }
    std::cout << report.str() << "\n";
    return 2;
}
