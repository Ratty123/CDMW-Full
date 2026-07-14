#include "texture_tool_internal.h"

#include <chrono>
#include <exception>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

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
    std::error_code size_error;
    const auto output_byte_size = fs::file_size(fs::path(job.output), size_error);
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
        << "\"output_byte_size\":" << (size_error ? 0 : output_byte_size) << ","
        << "\"encode_ms\":" << elapsed
        << "}";
    return out.str();
}
static std::string encode_dds_guarded(const EncodeJob& job) {
    try {
        return encode_dds(job);
    } catch (const std::exception& exc) {
        record_caught_exception("batch_encode_item_exception", "encode_dds", exc.what());
        return exception_item_json(job.input, job.output, "encode_dds", exc.what());
    } catch (...) {
        record_caught_exception("batch_encode_item_exception", "encode_dds", "unknown native exception");
        return exception_item_json(job.input, job.output, "encode_dds", "unknown native exception");
    }
}

static int batch_encode_json(const fs::path& job_file, const fs::path& report_file) {
    std::vector<EncodeJob> jobs = parse_encode_jobs(read_text_file(job_file));
    cdmw_native_diag::event("batch_encode_start", {{"job_file", cdmw_native_diag::path_to_utf8(job_file)}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}, {"batch_size", std::to_string(jobs.size())}});
    std::ostringstream report;
    report << "{\"status\":\"ok\",\"backend\":\"directxtex_native_0.1\",\"batch_size\":" << jobs.size() << ",\"items\":[";
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
        cdmw_native_diag::event("batch_encode_error", {{"reason", "failed to write report"}, {"report_file", cdmw_native_diag::path_to_utf8(report_file)}});
        return 3;
    }
    cdmw_native_diag::event("batch_encode_complete", {{"batch_size", std::to_string(jobs.size())}, {"any_error", any_error ? "true" : "false"}});
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
