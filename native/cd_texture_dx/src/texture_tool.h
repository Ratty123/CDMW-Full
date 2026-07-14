#pragma once

#include <filesystem>
#include <string>

struct CommonArgs {
    std::filesystem::path crash_dir;
    std::filesystem::path diagnostic_log;
};

CommonArgs parse_common_args(int argc, wchar_t** argv);
std::string wide_to_utf8(const std::wstring& text);
void record_caught_exception(const char* event_name, const char* operation, const char* message) noexcept;
bool json_parser_self_test();
int inspect_json(const std::wstring& source);
int batch_preview_json_guarded(
    const std::filesystem::path& job_file,
    const std::filesystem::path& report_file
);
int batch_encode_json_guarded(
    const std::filesystem::path& job_file,
    const std::filesystem::path& report_file
);

