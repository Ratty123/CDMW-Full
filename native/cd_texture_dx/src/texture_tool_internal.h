#pragma once

#include "texture_tool.h"

#include <DirectXTex.h>

#include <filesystem>
#include <string>
#include <vector>

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

std::wstring utf8_to_wide(const std::string& text);
std::string json_escape(const std::string& text);
std::string exception_item_json(
    const std::wstring& source,
    const std::wstring& output,
    const char* operation,
    const char* message
);
std::string read_text_file(const std::filesystem::path& path);
bool write_text_file(const std::filesystem::path& path, const std::string& text);
std::vector<PreviewJob> parse_jobs(const std::string& text);
std::vector<EncodeJob> parse_encode_jobs(const std::string& text);
DXGI_FORMAT dxgi_format_from_name(const std::string& raw_format);
std::string dxgi_format_name(DXGI_FORMAT format);
bool is_srgb_format(DXGI_FORMAT format);
bool is_bc_compressed_format(DXGI_FORMAT format);
std::string bc_family(DXGI_FORMAT format);
std::string metadata_json(
    const std::filesystem::path& source,
    const DirectX::TexMetadata& metadata,
    const char* status
);
int write_batch_exception_report(
    const std::filesystem::path& report_file,
    const char* operation,
    const char* message
);
