#pragma once

#include <Windows.h>
#include <DbgHelp.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <sstream>
#include <string>
#include <utility>

#pragma comment(lib, "Dbghelp.lib")

namespace cdmw_native_diag {
namespace fs = std::filesystem;

inline fs::path g_crash_dir;
inline fs::path g_diagnostic_log;
inline std::string g_tool = "native";
inline constexpr uintmax_t kMaxJsonlBytes = 5u * 1024u * 1024u;
inline constexpr int kRotationCount = 3;

inline std::string wide_to_utf8_diag(const std::wstring& text) {
    if (text.empty()) return "";
    int needed = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return "";
    std::string output(static_cast<size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed, nullptr, nullptr);
    return output;
}

inline std::string path_to_utf8(const fs::path& path) {
    return wide_to_utf8_diag(path.wstring());
}

inline std::string json_escape_diag(const std::string& text) {
    std::ostringstream out;
    for (unsigned char raw : text) {
        char ch = static_cast<char>(raw);
        switch (ch) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (raw < 0x20) {
                out << "\\u00";
                const char* hex = "0123456789abcdef";
                out << hex[(raw >> 4) & 0xF] << hex[raw & 0xF];
            } else {
                out << ch;
            }
            break;
        }
    }
    return out.str();
}

inline long long epoch_ms() {
    auto now = std::chrono::system_clock::now();
    return std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
}

inline fs::path rotated_path(const fs::path& path, int index) {
    return path.parent_path() / (path.filename().wstring() + L"." + std::to_wstring(index));
}

inline void rotate_jsonl_if_needed(const fs::path& path) {
    std::error_code ec;
    if (path.empty() || !fs::is_regular_file(path, ec) || fs::file_size(path, ec) < kMaxJsonlBytes) return;
    fs::remove(rotated_path(path, kRotationCount), ec);
    for (int index = kRotationCount - 1; index >= 1; --index) {
        fs::path previous = rotated_path(path, index);
        fs::path target = rotated_path(path, index + 1);
        if (fs::is_regular_file(previous, ec)) {
            fs::rename(previous, target, ec);
            if (ec) {
                ec.clear();
                fs::copy_file(previous, target, fs::copy_options::overwrite_existing, ec);
                fs::remove(previous, ec);
            }
        }
    }
    fs::rename(path, rotated_path(path, 1), ec);
    if (ec) {
        ec.clear();
        fs::copy_file(path, rotated_path(path, 1), fs::copy_options::overwrite_existing, ec);
        fs::remove(path, ec);
    }
}

inline void append_jsonl(const fs::path& path, const std::string& line) {
    if (path.empty()) return;
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    rotate_jsonl_if_needed(path);
    std::ofstream stream(path, std::ios::binary | std::ios::app);
    if (!stream) return;
    stream << line << "\n";
}

inline void event(const std::string& name, std::initializer_list<std::pair<std::string, std::string>> fields = {}) {
    if (g_diagnostic_log.empty()) return;
    std::ostringstream out;
    out << "{\"timestamp_ms\":" << epoch_ms()
        << ",\"pid\":" << static_cast<unsigned long>(GetCurrentProcessId())
        << ",\"tool\":\"" << json_escape_diag(g_tool) << "\""
        << ",\"event\":\"" << json_escape_diag(name) << "\"";
    for (const auto& field : fields) {
        out << ",\"" << json_escape_diag(field.first) << "\":\"" << json_escape_diag(field.second) << "\"";
    }
    out << "}";
    append_jsonl(g_diagnostic_log, out.str());
}

inline LONG WINAPI unhandled_exception_filter(EXCEPTION_POINTERS* info) {
    DWORD code = info && info->ExceptionRecord ? info->ExceptionRecord->ExceptionCode : 0;
    void* address = info && info->ExceptionRecord ? info->ExceptionRecord->ExceptionAddress : nullptr;
    std::ostringstream address_text;
    address_text << address;
    event("native_unhandled_exception", {{"code", std::to_string(code)}, {"address", address_text.str()}});
    if (!g_crash_dir.empty()) {
        std::error_code ec;
        fs::create_directories(g_crash_dir, ec);
        std::wstring base_name = L"native_crash_" + std::wstring(g_tool.begin(), g_tool.end()) + L"_" +
            std::to_wstring(GetCurrentProcessId()) + L"_" + std::to_wstring(epoch_ms());
        fs::path json_path = g_crash_dir / (base_name + L".json");
        std::ofstream json(json_path, std::ios::binary);
        if (json) {
            json << "{\"timestamp_ms\":" << epoch_ms()
                 << ",\"pid\":" << static_cast<unsigned long>(GetCurrentProcessId())
                 << ",\"tool\":\"" << json_escape_diag(g_tool) << "\""
                 << ",\"exception_code\":" << code
                 << ",\"exception_address\":\"" << json_escape_diag(address_text.str()) << "\""
                 << ",\"thread_id\":" << static_cast<unsigned long>(GetCurrentThreadId())
                 << "}\n";
        }
        fs::path dump_path = g_crash_dir / (base_name + L".dmp");
        HANDLE file = CreateFileW(dump_path.wstring().c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file != INVALID_HANDLE_VALUE) {
            MINIDUMP_EXCEPTION_INFORMATION dump_info{};
            dump_info.ThreadId = GetCurrentThreadId();
            dump_info.ExceptionPointers = info;
            dump_info.ClientPointers = FALSE;
            MiniDumpWriteDump(
                GetCurrentProcess(),
                GetCurrentProcessId(),
                file,
                MiniDumpNormal,
                info ? &dump_info : nullptr,
                nullptr,
                nullptr);
            CloseHandle(file);
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

inline void init(const std::string& tool, const fs::path& crash_dir, const fs::path& diagnostic_log) {
    g_tool = tool.empty() ? "native" : tool;
    g_crash_dir = crash_dir;
    g_diagnostic_log = diagnostic_log;
    SetUnhandledExceptionFilter(unhandled_exception_filter);
    event("diagnostics_initialized", {{"crash_dir", path_to_utf8(g_crash_dir)}, {"diagnostic_log", path_to_utf8(g_diagnostic_log)}});
}

} // namespace cdmw_native_diag
