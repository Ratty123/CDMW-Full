#include "cdmw_archive_core.h"
#include "archive_core_internal.hpp"

namespace {

void copy_text(const std::string& value, char* destination, size_t capacity) {
    if (destination == nullptr || capacity == 0) return;
    const size_t count = std::min(value.size(), capacity - 1);
    if (count > 0) std::memcpy(destination, value.data(), count);
    destination[count] = '\0';
}

void clear_text(char* destination, size_t capacity) {
    if (destination != nullptr && capacity > 0) destination[0] = '\0';
}

int classify_exception(const std::exception& exception, char* error, size_t error_capacity) {
    copy_text(exception.what(), error, error_capacity);
    if (dynamic_cast<const std::invalid_argument*>(&exception) != nullptr) return CDMW_ARCHIVE_INVALID_ARGUMENT;
    if (dynamic_cast<const cdmw::archive::UnsupportedError*>(&exception) != nullptr) return CDMW_ARCHIVE_UNSUPPORTED;
    if (dynamic_cast<const std::filesystem::filesystem_error*>(&exception) != nullptr) return CDMW_ARCHIVE_IO_ERROR;
    return CDMW_ARCHIVE_FORMAT_ERROR;
}

}  // namespace

extern "C" {

std::uint32_t cdmw_archive_core_abi_version(void) {
    return CDMW_ARCHIVE_CORE_ABI_VERSION;
}

int cdmw_archive_build_index_utf8(
    const char* package_root,
    const char* index_path,
    std::uint64_t* entry_count,
    char* error_message,
    size_t error_message_capacity) {
    clear_text(error_message, error_message_capacity);
    if (entry_count == nullptr) {
        copy_text("entry_count must not be null", error_message, error_message_capacity);
        return CDMW_ARCHIVE_INVALID_ARGUMENT;
    }
    *entry_count = 0;
    try {
        const auto entries = cdmw::archive::scan_package_root(cdmw::archive::utf8_path(package_root));
        cdmw::archive::write_index_atomic(cdmw::archive::utf8_path(index_path), entries);
        *entry_count = entries.size();
        return CDMW_ARCHIVE_OK;
    } catch (const std::exception& exception) {
        return classify_exception(exception, error_message, error_message_capacity);
    } catch (...) {
        copy_text("unknown native archive failure", error_message, error_message_capacity);
        return CDMW_ARCHIVE_FORMAT_ERROR;
    }
}

int cdmw_archive_decode_entry_utf8(
    const char* virtual_path,
    const char* paz_path,
    std::uint64_t archive_offset,
    std::uint64_t stored_size,
    std::uint64_t original_size,
    std::uint32_t flags,
    std::uint8_t* output,
    size_t output_capacity,
    size_t* required_size,
    char* note,
    size_t note_capacity,
    char* error_message,
    size_t error_message_capacity) {
    clear_text(note, note_capacity);
    clear_text(error_message, error_message_capacity);
    if (required_size == nullptr || virtual_path == nullptr || *virtual_path == '\0') {
        copy_text("required_size and virtual_path must not be null", error_message, error_message_capacity);
        return CDMW_ARCHIVE_INVALID_ARGUMENT;
    }
    *required_size = 0;
    try {
        const auto decoded = cdmw::archive::decode_entry(
            virtual_path,
            {},
            cdmw::archive::utf8_path(paz_path),
            archive_offset,
            stored_size,
            original_size,
            flags);
        *required_size = decoded.bytes.size();
        copy_text(decoded.note, note, note_capacity);
        if (output == nullptr) return CDMW_ARCHIVE_OK;
        if (output_capacity < decoded.bytes.size()) {
            copy_text("output buffer is too small", error_message, error_message_capacity);
            return CDMW_ARCHIVE_BUFFER_TOO_SMALL;
        }
        if (!decoded.bytes.empty()) std::memcpy(output, decoded.bytes.data(), decoded.bytes.size());
        return CDMW_ARCHIVE_OK;
    } catch (const std::exception& exception) {
        return classify_exception(exception, error_message, error_message_capacity);
    } catch (...) {
        copy_text("unknown native archive failure", error_message, error_message_capacity);
        return CDMW_ARCHIVE_FORMAT_ERROR;
    }
}

int cdmw_archive_decode_entry_with_context_utf8(
    const char* virtual_path,
    const char* pamt_path,
    const char* paz_path,
    std::uint64_t archive_offset,
    std::uint64_t stored_size,
    std::uint64_t original_size,
    std::uint32_t flags,
    std::uint8_t* output,
    size_t output_capacity,
    size_t* required_size,
    char* note,
    size_t note_capacity,
    char* error_message,
    size_t error_message_capacity) {
    clear_text(note, note_capacity);
    clear_text(error_message, error_message_capacity);
    if (required_size == nullptr || virtual_path == nullptr || *virtual_path == '\0' ||
        pamt_path == nullptr || *pamt_path == '\0') {
        copy_text("required_size, virtual_path, and pamt_path must not be null", error_message, error_message_capacity);
        return CDMW_ARCHIVE_INVALID_ARGUMENT;
    }
    *required_size = 0;
    try {
        const auto decoded = cdmw::archive::decode_entry(
            virtual_path,
            cdmw::archive::utf8_path(pamt_path),
            cdmw::archive::utf8_path(paz_path),
            archive_offset,
            stored_size,
            original_size,
            flags);
        *required_size = decoded.bytes.size();
        copy_text(decoded.note, note, note_capacity);
        if (output == nullptr) return CDMW_ARCHIVE_OK;
        if (output_capacity < decoded.bytes.size()) {
            copy_text("output buffer is too small", error_message, error_message_capacity);
            return CDMW_ARCHIVE_BUFFER_TOO_SMALL;
        }
        if (!decoded.bytes.empty()) std::memcpy(output, decoded.bytes.data(), decoded.bytes.size());
        return CDMW_ARCHIVE_OK;
    } catch (const std::exception& exception) {
        return classify_exception(exception, error_message, error_message_capacity);
    } catch (...) {
        copy_text("unknown native archive failure", error_message, error_message_capacity);
        return CDMW_ARCHIVE_FORMAT_ERROR;
    }
}

}  // extern "C"
