#include "texture_tool_internal.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cctype>
#include <exception>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

namespace {

std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

std::string encode_error(const EncodeJob& job, const std::string& message) {
    return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.2\",\"source_path\":\"" +
        json_escape(wide_to_utf8(job.input)) + "\",\"output_path\":\"" +
        json_escape(wide_to_utf8(job.output)) + "\",\"message\":\"" + json_escape(message) + "\"}";
}

std::string hresult_message(const char* operation, HRESULT hr) {
    std::ostringstream out;
    out << operation << " failed: 0x" << std::hex << static_cast<unsigned int>(hr);
    return out.str();
}

DirectX::TEX_FILTER_FLAGS mip_filter_flags(const EncodeJob& job) {
    unsigned int flags = static_cast<unsigned int>(DirectX::TEX_FILTER_DEFAULT);
    if (lower_copy(job.mip_alpha_policy) == "separate") {
        flags |= static_cast<unsigned int>(DirectX::TEX_FILTER_SEPARATE_ALPHA);
    }
    return static_cast<DirectX::TEX_FILTER_FLAGS>(flags);
}

DirectX::TEX_ALPHA_MODE alpha_mode_from_name(const std::string& raw_mode) {
    const std::string mode = lower_copy(raw_mode);
    if (mode == "straight") return DirectX::TEX_ALPHA_MODE_STRAIGHT;
    if (mode == "premultiplied") return DirectX::TEX_ALPHA_MODE_PREMULTIPLIED;
    if (mode == "opaque") return DirectX::TEX_ALPHA_MODE_OPAQUE;
    if (mode == "custom") return DirectX::TEX_ALPHA_MODE_CUSTOM;
    return DirectX::TEX_ALPHA_MODE_UNKNOWN;
}

DXGI_FORMAT intermediate_format_for_target(DXGI_FORMAT target_format) {
    switch (target_format) {
    case DXGI_FORMAT_BC6H_UF16:
    case DXGI_FORMAT_BC6H_SF16:
        return DXGI_FORMAT_R16G16B16A16_FLOAT;
    case DXGI_FORMAT_BC4_SNORM:
    case DXGI_FORMAT_BC5_SNORM:
        return DXGI_FORMAT_R16G16B16A16_FLOAT;
    default:
        if (DirectX::IsCompressed(target_format)) {
            return is_srgb_format(target_format)
                ? DXGI_FORMAT_R8G8B8A8_UNORM_SRGB
                : DXGI_FORMAT_R8G8B8A8_UNORM;
        }
        return target_format;
    }
}

size_t maximum_mip_count(size_t width, size_t height) {
    size_t levels = 1;
    while (width > 1 || height > 1) {
        width = std::max<size_t>(1, width / 2);
        height = std::max<size_t>(1, height / 2);
        ++levels;
    }
    return levels;
}

}  // namespace

std::string encode_dds_job(const EncodeJob& job) {
    const auto started = std::chrono::steady_clock::now();
    if (!job.overwrite && fs::exists(fs::path(job.output))) {
        return encode_error(job, "output exists and overwrite=false");
    }

    const DXGI_FORMAT target_format = dxgi_format_from_name(job.format);
    if (target_format == DXGI_FORMAT_UNKNOWN) {
        return encode_error(job, "unsupported DDS format " + job.format);
    }

    const std::string source_color_policy = lower_copy(job.source_color_policy);
    if (source_color_policy != "auto" && source_color_policy != "ignore_srgb_metadata") {
        return encode_error(job, "unsupported source_color_policy " + job.source_color_policy);
    }
    const std::string mip_alpha_policy = lower_copy(job.mip_alpha_policy);
    if (mip_alpha_policy != "default" && mip_alpha_policy != "separate" &&
        mip_alpha_policy != "preserve_coverage") {
        return encode_error(job, "unsupported mip_alpha_policy " + job.mip_alpha_policy);
    }
    const std::string dds_alpha_mode = lower_copy(job.dds_alpha_mode);
    if (dds_alpha_mode != "unknown" && dds_alpha_mode != "straight" &&
        dds_alpha_mode != "premultiplied" && dds_alpha_mode != "opaque" &&
        dds_alpha_mode != "custom") {
        return encode_error(job, "unsupported dds_alpha_mode " + job.dds_alpha_mode);
    }

    DirectX::WIC_FLAGS wic_flags = DirectX::WIC_FLAGS_NONE;
    if (source_color_policy == "ignore_srgb_metadata") {
        wic_flags = static_cast<DirectX::WIC_FLAGS>(
            static_cast<unsigned int>(wic_flags) |
            static_cast<unsigned int>(DirectX::WIC_FLAGS_IGNORE_SRGB)
        );
    }

    DirectX::ScratchImage source_image;
    DirectX::TexMetadata source_metadata{};
    HRESULT hr = DirectX::LoadFromWICFile(job.input.c_str(), wic_flags, &source_metadata, source_image);
    if (FAILED(hr)) {
        return encode_error(job, hresult_message("LoadFromWICFile", hr));
    }
    const DirectX::Image* image = source_image.GetImage(0, 0, 0);
    if (!image) {
        return encode_error(job, "input image has no first frame");
    }

    const DXGI_FORMAT intermediate_format = intermediate_format_for_target(target_format);
    DirectX::ScratchImage converted;
    DirectX::ScratchImage* working = &source_image;
    if (image->format != intermediate_format) {
        hr = DirectX::Convert(
            *image,
            intermediate_format,
            mip_filter_flags(job),
            DirectX::TEX_THRESHOLD_DEFAULT,
            converted
        );
        if (FAILED(hr)) {
            return encode_error(job, hresult_message("Convert", hr));
        }
        working = &converted;
        image = working->GetImage(0, 0, 0);
    }
    if (!image) {
        return encode_error(job, "converted image is empty");
    }

    DirectX::ScratchImage resized;
    const size_t target_width = job.width > 0 ? static_cast<size_t>(job.width) : image->width;
    const size_t target_height = job.height > 0 ? static_cast<size_t>(job.height) : image->height;
    if (target_width == 0 || target_height == 0) {
        return encode_error(job, "target dimensions must be positive");
    }
    if (target_width != image->width || target_height != image->height) {
        hr = DirectX::Resize(*image, target_width, target_height, mip_filter_flags(job), resized);
        if (FAILED(hr)) {
            return encode_error(job, hresult_message("Resize", hr));
        }
        working = &resized;
        image = working->GetImage(0, 0, 0);
    }
    if (!image) {
        return encode_error(job, "resized image is empty");
    }

    DirectX::ScratchImage mip_chain;
    const size_t max_mips = maximum_mip_count(target_width, target_height);
    const size_t requested_mips = job.mip_count == 0
        ? 0
        : std::min(max_mips, static_cast<size_t>(std::max(1, job.mip_count)));
    if (job.mip_count == 0 || requested_mips > 1) {
        hr = DirectX::GenerateMipMaps(*image, mip_filter_flags(job), requested_mips, mip_chain);
        if (FAILED(hr)) {
            return encode_error(job, hresult_message("GenerateMipMaps", hr));
        }
        working = &mip_chain;
    }

    DirectX::ScratchImage coverage_adjusted;
    if (mip_alpha_policy == "preserve_coverage" && working->GetMetadata().mipLevels > 1) {
        const DirectX::TexMetadata& metadata = working->GetMetadata();
        hr = coverage_adjusted.Initialize(metadata);
        if (FAILED(hr)) {
            return encode_error(job, hresult_message("Initialize alpha coverage chain", hr));
        }
        for (size_t item = 0; item < metadata.arraySize; ++item) {
            const DirectX::Image* base = working->GetImage(0, item, 0);
            if (!base) {
                return encode_error(job, "alpha coverage source image is empty");
            }
            hr = DirectX::ScaleMipMapsAlphaForCoverage(
                base,
                metadata.mipLevels,
                metadata,
                item,
                job.alpha_coverage_reference,
                coverage_adjusted
            );
            if (FAILED(hr)) {
                return encode_error(job, hresult_message("ScaleMipMapsAlphaForCoverage", hr));
            }
        }
        working = &coverage_adjusted;
    }

    DirectX::ScratchImage compressed_or_final;
    DirectX::ScratchImage* final_image = working;
    if (DirectX::IsCompressed(target_format)) {
        hr = DirectX::Compress(
            working->GetImages(),
            working->GetImageCount(),
            working->GetMetadata(),
            target_format,
            DirectX::TEX_COMPRESS_PARALLEL,
            DirectX::TEX_THRESHOLD_DEFAULT,
            compressed_or_final
        );
        if (FAILED(hr)) {
            return encode_error(job, hresult_message("Compress", hr));
        }
        final_image = &compressed_or_final;
    } else if (working->GetMetadata().format != target_format) {
        hr = DirectX::Convert(
            working->GetImages(),
            working->GetImageCount(),
            working->GetMetadata(),
            target_format,
            mip_filter_flags(job),
            DirectX::TEX_THRESHOLD_DEFAULT,
            compressed_or_final
        );
        if (FAILED(hr)) {
            return encode_error(job, hresult_message("Final Convert", hr));
        }
        final_image = &compressed_or_final;
    }

    DirectX::TexMetadata output_metadata = final_image->GetMetadata();
    output_metadata.SetAlphaMode(alpha_mode_from_name(dds_alpha_mode));
    const DirectX::DDS_FLAGS dds_flags = output_metadata.GetAlphaMode() == DirectX::TEX_ALPHA_MODE_UNKNOWN
        ? DirectX::DDS_FLAGS_NONE
        : DirectX::DDS_FLAGS_FORCE_DX10_EXT_MISC2;

    std::error_code ec;
    fs::create_directories(fs::path(job.output).parent_path(), ec);
    hr = DirectX::SaveToDDSFile(
        final_image->GetImages(),
        final_image->GetImageCount(),
        output_metadata,
        dds_flags,
        job.output.c_str()
    );
    const auto elapsed = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started
    ).count();
    if (FAILED(hr)) {
        return encode_error(job, hresult_message("SaveToDDSFile", hr));
    }

    std::error_code size_error;
    const auto output_byte_size = fs::file_size(fs::path(job.output), size_error);
    std::ostringstream out;
    out << "{"
        << "\"status\":\"encoded\","
        << "\"protocol_version\":2,"
        << "\"backend\":\"directxtex_native_0.2\","
        << "\"native_backend\":\"directxtex\","
        << "\"source_path\":\"" << json_escape(wide_to_utf8(job.input)) << "\","
        << "\"output_path\":\"" << json_escape(wide_to_utf8(job.output)) << "\","
        << "\"format\":\"" << dxgi_format_name(output_metadata.format) << "\","
        << "\"requested_format\":\"" << json_escape(job.format) << "\","
        << "\"dxgi_format\":" << static_cast<unsigned int>(output_metadata.format) << ","
        << "\"compressed\":" << (DirectX::IsCompressed(output_metadata.format) ? "true" : "false") << ","
        << "\"compressed_family\":\"" << json_escape(bc_family(output_metadata.format)) << "\","
        << "\"srgb\":" << (is_srgb_format(output_metadata.format) ? "true" : "false") << ","
        << "\"width\":" << output_metadata.width << ","
        << "\"height\":" << output_metadata.height << ","
        << "\"mip_count\":" << output_metadata.mipLevels << ","
        << "\"source_color_policy\":\"" << json_escape(source_color_policy) << "\","
        << "\"mip_alpha_policy\":\"" << json_escape(mip_alpha_policy) << "\","
        << "\"alpha_coverage_reference\":" << job.alpha_coverage_reference << ","
        << "\"dds_alpha_mode\":\"" << alpha_mode_name(output_metadata.GetAlphaMode()) << "\","
        << "\"output_byte_size\":" << (size_error ? 0 : output_byte_size) << ","
        << "\"encode_ms\":" << elapsed
        << "}";
    return out.str();
}

static std::string encode_dds_guarded(const EncodeJob& job) {
    try {
        return encode_dds_job(job);
    } catch (const std::exception& exc) {
        record_caught_exception("batch_encode_item_exception", "encode_dds", exc.what());
        return exception_item_json(job.input, job.output, "encode_dds", exc.what());
    } catch (...) {
        record_caught_exception("batch_encode_item_exception", "encode_dds", "unknown native exception");
        return exception_item_json(job.input, job.output, "encode_dds", "unknown native exception");
    }
}

static int batch_encode_json(const fs::path& job_file, const fs::path& report_file) {
    const std::vector<EncodeJob> jobs = parse_encode_jobs(read_text_file(job_file));
    cdmw_native_diag::event(
        "batch_encode_start",
        {
            {"job_file", cdmw_native_diag::path_to_utf8(job_file)},
            {"report_file", cdmw_native_diag::path_to_utf8(report_file)},
            {"batch_size", std::to_string(jobs.size())},
        }
    );
    std::ostringstream report;
    report << "{\"status\":\"ok\",\"protocol_version\":2,\"backend\":\"directxtex_native_0.2\","
        << "\"batch_size\":" << jobs.size() << ",\"items\":[";
    bool any_error = false;
    for (size_t index = 0; index < jobs.size(); ++index) {
        if (index) report << ",";
        const std::string item = encode_dds_guarded(jobs[index]);
        if (item.find("\"status\":\"error\"") != std::string::npos) any_error = true;
        report << item;
    }
    report << "]}";
    if (!write_text_file(report_file, report.str())) {
        std::cerr << "failed to write report: " << report_file << "\n";
        cdmw_native_diag::event(
            "batch_encode_error",
            {{"reason", "failed to write report"}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}}
        );
        return 3;
    }
    cdmw_native_diag::event(
        "batch_encode_complete",
        {{"batch_size", std::to_string(jobs.size())}, {"any_error", any_error ? "true" : "false"}}
    );
    std::cout << report.str() << "\n";
    return any_error ? 2 : 0;
}

int batch_encode_json_guarded(const fs::path& job_file, const fs::path& report_file) {
    try {
        return batch_encode_json(job_file, report_file);
    } catch (const std::exception& exc) {
        record_caught_exception("batch_encode_exception", "batch_encode_json", exc.what());
        return write_batch_exception_report(report_file, "batch_encode_json", exc.what());
    } catch (...) {
        record_caught_exception("batch_encode_exception", "batch_encode_json", "unknown native exception");
        return write_batch_exception_report(report_file, "batch_encode_json", "unknown native exception");
    }
}
