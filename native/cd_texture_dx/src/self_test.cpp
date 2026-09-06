#include "texture_tool_internal.h"

#include <wincodec.h>

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <string>

namespace fs = std::filesystem;

namespace {

bool encoded_ok(const std::string& report) {
    return report.find("\"status\":\"encoded\"") != std::string::npos;
}

bool decoded_ok(const std::string& report) {
    return report.find("\"status\":\"decoded\"") != std::string::npos;
}

}  // namespace

static const char* write_color_source_png(const fs::path& source_png) {
    DirectX::ScratchImage color_source;
    HRESULT hr = color_source.Initialize2D(DXGI_FORMAT_R8G8B8A8_UNORM, 32, 32, 1, 1);
    if (FAILED(hr)) return "initialize_color_source";
    const DirectX::Image* color_frame = color_source.GetImage(0, 0, 0);
    if (!color_frame) return "get_color_frame";
    for (size_t y = 0; y < color_frame->height; ++y) {
        uint8_t* row = color_frame->pixels + y * color_frame->rowPitch;
        for (size_t x = 0; x < color_frame->width; ++x) {
            uint8_t* pixel = row + x * 4;
            pixel[0] = static_cast<uint8_t>((x * 17 + y * 3) & 0xff);
            pixel[1] = static_cast<uint8_t>((x * 5 + y * 13) & 0xff);
            pixel[2] = static_cast<uint8_t>((x * 11 + y * 7) & 0xff);
            pixel[3] = static_cast<uint8_t>(((x / 4 + y / 4) % 2) ? 255 : 32);
        }
    }

    hr = DirectX::SaveToWICFile(
        *color_frame,
        DirectX::WIC_FLAGS_NONE,
        GUID_ContainerFormatPng,
        source_png.c_str(),
        nullptr
    );
    if (FAILED(hr)) return "save_source_png";
    return nullptr;
}

static const char* assumed_srgb_policy_failure(const fs::path& root) {
    constexpr uint8_t untagged_png_bytes[] = {
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
        0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
        0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41,
        0x54, 0x78, 0x9c, 0x63, 0x68, 0x70, 0x50, 0x10,
        0x04, 0x00, 0x03, 0x16, 0x00, 0xf2, 0xc0, 0xb4,
        0x97, 0xe4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
        0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    };
    const fs::path untagged_png = root / L"untagged-source.png";
    if (!write_text_file(
            untagged_png,
            std::string(
                reinterpret_cast<const char*>(untagged_png_bytes),
                sizeof(untagged_png_bytes)
            ))) {
        return "write_untagged_source_png";
    }

    EncodeJob assumed_srgb_job;
    assumed_srgb_job.input = untagged_png.wstring();
    assumed_srgb_job.output = (root / L"assumed-srgb.dds").wstring();
    assumed_srgb_job.format = "R8G8B8A8_UNORM_SRGB";
    assumed_srgb_job.source_color_policy = "assume_srgb";
    if (!encoded_ok(encode_dds_job(assumed_srgb_job))) {
        return "encode_assumed_srgb";
    }
    DirectX::ScratchImage assumed_srgb;
    DirectX::TexMetadata assumed_srgb_metadata{};
    const HRESULT hr = DirectX::LoadFromDDSFile(
        assumed_srgb_job.output.c_str(),
        DirectX::DDS_FLAGS_NONE,
        &assumed_srgb_metadata,
        assumed_srgb
    );
    if (FAILED(hr) || assumed_srgb_metadata.format != DXGI_FORMAT_R8G8B8A8_UNORM_SRGB) {
        return "load_assumed_srgb";
    }
    const DirectX::Image* assumed_srgb_frame = assumed_srgb.GetImage(0, 0, 0);
    if (!assumed_srgb_frame) return "get_assumed_srgb_frame";
    constexpr uint8_t expected_assumed_srgb[] = {128, 64, 32, 17};
    for (size_t channel = 0; channel < 4; ++channel) {
        if (assumed_srgb_frame->pixels[channel] != expected_assumed_srgb[channel]) {
            return "compare_assumed_srgb_numeric_bytes";
        }
    }
    return nullptr;
}

bool texture_codec_self_test(std::string& failed_component) {
    if (win32_file_path(L"C:\\cache\\.\\maps\\..\\base.dds") != L"\\\\?\\C:\\cache\\base.dds" ||
        win32_file_path(L"\\\\server\\share\\base.dds") != L"\\\\?\\UNC\\server\\share\\base.dds" ||
        win32_file_path(L"\\\\?\\C:\\cache\\base.dds") != L"\\\\?\\C:\\cache\\base.dds") {
        failed_component = "win32_file_paths";
        return false;
    }
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
    const fs::path root = fs::temp_directory_path() /
        (L"cd_texture_dx_self_test_" + std::to_wstring(nonce));
    std::error_code ec;
    fs::create_directories(root, ec);
    if (ec) {
        failed_component = "create_temp_directory";
        return false;
    }

    auto finish = [&](bool ok, const char* component) {
        if (!ok) failed_component = component;
        std::error_code cleanup_error;
        fs::remove_all(root, cleanup_error);
        return ok;
    };

    const fs::path source_png = root / L"source.png";
    if (const char* failure = write_color_source_png(source_png)) return finish(false, failure);
    if (const char* failure = assumed_srgb_policy_failure(root)) return finish(false, failure);
    HRESULT hr = S_OK;

    EncodeJob linear_job;
    linear_job.input = source_png.wstring();
    linear_job.output = (root / L"linear.dds").wstring();
    linear_job.format = "BC7_UNORM";
    linear_job.mip_count = 6;
    linear_job.mip_alpha_policy = "separate";
    linear_job.dds_alpha_mode = "opaque";
    if (!encoded_ok(encode_dds_job(linear_job))) {
        return finish(false, "encode_bc7_linear_separate_alpha");
    }

    EncodeJob srgb_job;
    srgb_job.input = source_png.wstring();
    srgb_job.output = (root / L"srgb.dds").wstring();
    srgb_job.format = "BC7_UNORM_SRGB";
    srgb_job.mip_count = 6;
    srgb_job.source_color_policy = "ignore_srgb_metadata";
    srgb_job.mip_alpha_policy = "preserve_coverage";
    srgb_job.alpha_coverage_reference = 0.5f;
    srgb_job.dds_alpha_mode = "straight";
    if (!encoded_ok(encode_dds_job(srgb_job))) {
        return finish(false, "encode_bc7_srgb_coverage");
    }

    DirectX::ScratchImage inspected;
    DirectX::TexMetadata inspected_metadata{};
    hr = DirectX::LoadFromDDSFile(
        srgb_job.output.c_str(),
        DirectX::DDS_FLAGS_NONE,
        &inspected_metadata,
        inspected
    );
    if (FAILED(hr)) return finish(false, "load_bc7_srgb");
    if (inspected_metadata.format != DXGI_FORMAT_BC7_UNORM_SRGB) {
        return finish(false, "inspect_bc7_srgb_format");
    }
    if (inspected_metadata.width != 32 || inspected_metadata.height != 32) {
        return finish(false, "inspect_bc7_srgb_dimensions");
    }
    if (inspected_metadata.mipLevels != 6) {
        return finish(false, "inspect_bc7_srgb_mips");
    }
    if (inspected_metadata.GetAlphaMode() != DirectX::TEX_ALPHA_MODE_STRAIGHT) {
        return finish(false, "inspect_bc7_srgb_alpha_mode");
    }

    PreviewJob mip_job;
    mip_job.input = srgb_job.output;
    mip_job.output = (root / L"mip3.png").wstring();
    mip_job.max_dimension = 0;
    mip_job.requested_mip = 3;
    mip_job.output_pixel_type = "rgba8";
    if (!decoded_ok(decode_preview_job(mip_job)) || !fs::is_regular_file(fs::path(mip_job.output))) {
        return finish(false, "decode_selected_mip");
    }

    DirectX::ScratchImage gray_source;
    hr = gray_source.Initialize2D(DXGI_FORMAT_R16_UNORM, 16, 16, 1, 1);
    if (FAILED(hr)) return finish(false, "initialize_gray16_source");
    const DirectX::Image* gray_frame = gray_source.GetImage(0, 0, 0);
    if (!gray_frame) return finish(false, "get_gray16_frame");
    for (size_t y = 0; y < gray_frame->height; ++y) {
        auto* row = reinterpret_cast<uint16_t*>(gray_frame->pixels + y * gray_frame->rowPitch);
        for (size_t x = 0; x < gray_frame->width; ++x) {
            row[x] = static_cast<uint16_t>((x * 4096 + y * 257) & 0xffff);
        }
    }
    const fs::path gray_dds = root / L"gray16.dds";
    hr = DirectX::SaveToDDSFile(
        gray_source.GetImages(),
        gray_source.GetImageCount(),
        gray_source.GetMetadata(),
        DirectX::DDS_FLAGS_NONE,
        gray_dds.c_str()
    );
    if (FAILED(hr)) return finish(false, "save_gray16_dds");

    PreviewJob gray_job;
    gray_job.input = gray_dds.wstring();
    gray_job.output = (root / L"gray16.png").wstring();
    gray_job.max_dimension = 0;
    gray_job.output_pixel_type = "gray16";
    if (!decoded_ok(decode_preview_job(gray_job))) {
        return finish(false, "decode_gray16");
    }
    DirectX::ScratchImage gray_roundtrip;
    DirectX::TexMetadata gray_metadata{};
    hr = DirectX::LoadFromWICFile(
        gray_job.output.c_str(),
        DirectX::WIC_FLAGS_NONE,
        &gray_metadata,
        gray_roundtrip
    );
    if (FAILED(hr) || gray_metadata.format != DXGI_FORMAT_R16_UNORM) {
        return finish(false, "inspect_gray16_png");
    }

    return finish(true, "");
}
