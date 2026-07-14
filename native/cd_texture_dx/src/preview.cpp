#include "texture_tool_internal.h"

#include <wincodec.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <exception>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

static bool should_invert_green(const PreviewJob& job) {
    std::string slot = job.slot;
    std::string normal_space = job.normal_space;
    std::transform(slot.begin(), slot.end(), slot.begin(), ::tolower);
    std::transform(normal_space.begin(), normal_space.end(), normal_space.begin(), ::tolower);
    return slot == "normal" && (normal_space == "green_up" || normal_space == "auto");
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

    DirectX::ScratchImage decompressed;
    const DirectX::Image* convert_source = first;
    if (DirectX::IsCompressed(first->format)) {
        hr = DirectX::Decompress(*first, DXGI_FORMAT_R8G8B8A8_UNORM, decompressed);
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"Decompress BC failed: 0x" +
                std::to_string(static_cast<unsigned int>(hr)) + "\"}";
        }
        convert_source = decompressed.GetImage(0, 0, 0);
    }
    if (!convert_source) {
        return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
            json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"DDS conversion source is empty\"}";
    }

    DirectX::ScratchImage rgba;
    DirectX::ScratchImage* output_image = &rgba;
    if (convert_source->format == DXGI_FORMAT_R8G8B8A8_UNORM) {
        hr = rgba.InitializeFromImage(*convert_source);
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"Initialize RGBA8 failed: 0x" +
                std::to_string(static_cast<unsigned int>(hr)) + "\"}";
        }
    } else {
        hr = DirectX::Convert(*convert_source, DXGI_FORMAT_R8G8B8A8_UNORM, DirectX::TEX_FILTER_DEFAULT, DirectX::TEX_THRESHOLD_DEFAULT, rgba);
        if (FAILED(hr)) {
            return "{\"status\":\"error\",\"backend\":\"directxtex_native_0.1\",\"source_path\":\"" +
                json_escape(wide_to_utf8(job.input)) + "\",\"message\":\"Convert RGBA8 failed: 0x" +
                std::to_string(static_cast<unsigned int>(hr)) + "; source_format=" +
                std::to_string(static_cast<unsigned int>(convert_source->format)) + "\"}";
        }
    }

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
        << "\"normal_space\":\"" << (normal_green_inverted ? "green_up_inverted" : job.normal_space) << "\","
        << "\"normal_green_inverted\":" << (normal_green_inverted ? "true" : "false") << ","
        << "\"decode_ms\":" << elapsed
        << "}";
    return out.str();
}

static std::string decode_preview_guarded(const PreviewJob& job) {
    try {
        return decode_preview(job);
    } catch (const std::exception& exc) {
        record_caught_exception("batch_preview_item_exception", "decode_preview", exc.what());
        return exception_item_json(job.input, job.output, "decode_preview", exc.what());
    } catch (...) {
        record_caught_exception("batch_preview_item_exception", "decode_preview", "unknown native exception");
        return exception_item_json(job.input, job.output, "decode_preview", "unknown native exception");
    }
}

int inspect_json(const std::wstring& source) {
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
        const std::string item = decode_preview_guarded(jobs[index]);
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

int batch_preview_json_guarded(const fs::path& job_file, const fs::path& report_file) {
    try {
        return batch_preview_json(job_file, report_file);
    } catch (const std::exception& exc) {
        record_caught_exception("batch_preview_exception", "batch_preview_json", exc.what());
        return write_batch_exception_report(report_file, "batch_preview_json", exc.what());
    } catch (...) {
        record_caught_exception("batch_preview_exception", "batch_preview_json", "unknown native exception");
        return write_batch_exception_report(report_file, "batch_preview_json", "unknown native exception");
    }
}
