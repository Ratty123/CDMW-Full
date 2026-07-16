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
    std::string normal_space = "auto";
    int max_dimension = 4096;
    int requested_mip = 0;
    std::string output_pixel_type = "rgba8";
};

struct EncodeJob {
    std::wstring input;
    std::wstring output;
    std::string format = "BC7_UNORM";
    int width = 0;
    int height = 0;
    int mip_count = 1;
    bool overwrite = true;
    std::string source_color_policy = "auto";
    std::string mip_alpha_policy = "default";
    float alpha_coverage_reference = 0.5f;
    std::string dds_alpha_mode = "unknown";
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
std::string alpha_mode_name(DirectX::TEX_ALPHA_MODE mode);
std::string metadata_json(
    const std::filesystem::path& source,
    const DirectX::TexMetadata& metadata,
    const char* status
);
std::string encode_dds_job(const EncodeJob& job);
std::string decode_preview_job(const PreviewJob& job);
bool texture_codec_self_test(std::string& failed_component);
int write_batch_exception_report(
    const std::filesystem::path& report_file,
    const char* operation,
    const char* message
);
