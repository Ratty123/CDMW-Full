#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(CDMW_ARCHIVE_CORE_EXPORTS)
#    define CDMW_ARCHIVE_API __declspec(dllexport)
#  else
#    define CDMW_ARCHIVE_API __declspec(dllimport)
#  endif
#else
#  define CDMW_ARCHIVE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

enum {
    CDMW_ARCHIVE_CORE_ABI_VERSION = 1,
    CDMW_ARCHIVE_INDEX_VERSION = 1,
    CDMW_ARCHIVE_OK = 0,
    CDMW_ARCHIVE_INVALID_ARGUMENT = 1,
    CDMW_ARCHIVE_IO_ERROR = 2,
    CDMW_ARCHIVE_FORMAT_ERROR = 3,
    CDMW_ARCHIVE_UNSUPPORTED = 4,
    CDMW_ARCHIVE_BUFFER_TOO_SMALL = 5,
};

CDMW_ARCHIVE_API uint32_t cdmw_archive_core_abi_version(void);

/*
 * Builds archive_index_v1 at index_path. Both paths are UTF-8. The source
 * archive tree is opened read-only; only index_path and its sibling staging
 * file can be written.
 */
CDMW_ARCHIVE_API int cdmw_archive_build_index_utf8(
    const char* package_root,
    const char* index_path,
    uint64_t* entry_count,
    char* error_message,
    size_t error_message_capacity);

/*
 * Decodes one archive entry into a caller-owned buffer. Call first with a null
 * output buffer to obtain required_size. The PAZ and virtual paths are UTF-8.
 */
CDMW_ARCHIVE_API int cdmw_archive_decode_entry_utf8(
    const char* virtual_path,
    const char* paz_path,
    uint64_t archive_offset,
    uint64_t stored_size,
    uint64_t original_size,
    uint32_t flags,
    uint8_t* output,
    size_t output_capacity,
    size_t* required_size,
    char* note,
    size_t note_capacity,
    char* error_message,
    size_t error_message_capacity);

/*
 * Context-aware decode used by Archive Lite. pamt_path is needed only for
 * partial DDS reconstruction through the sibling meta/0.pathc table. Passing
 * an empty pamt path preserves the context-free behavior above.
 */
CDMW_ARCHIVE_API int cdmw_archive_decode_entry_with_context_utf8(
    const char* virtual_path,
    const char* pamt_path,
    const char* paz_path,
    uint64_t archive_offset,
    uint64_t stored_size,
    uint64_t original_size,
    uint32_t flags,
    uint8_t* output,
    size_t output_capacity,
    size_t* required_size,
    char* note,
    size_t note_capacity,
    char* error_message,
    size_t error_message_capacity);

#ifdef __cplusplus
}
#endif
