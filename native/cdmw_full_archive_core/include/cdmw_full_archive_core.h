#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(CDMW_FULL_ARCHIVE_CORE_EXPORTS)
#    define CDMW_FULL_ARCHIVE_API __declspec(dllexport)
#  else
#    define CDMW_FULL_ARCHIVE_API __declspec(dllimport)
#  endif
#else
#  define CDMW_FULL_ARCHIVE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

enum {
    CDMW_FULL_ARCHIVE_CORE_ABI_VERSION = 1,
    CDMW_FULL_ARCHIVE_INDEX_VERSION = 2,
    CDMW_FULL_ARCHIVE_OK = 0,
    CDMW_FULL_ARCHIVE_INVALID_ARGUMENT = 1,
    CDMW_FULL_ARCHIVE_IO_ERROR = 2,
    CDMW_FULL_ARCHIVE_FORMAT_ERROR = 3,
    CDMW_FULL_ARCHIVE_UNSUPPORTED = 4,
    CDMW_FULL_ARCHIVE_BUFFER_TOO_SMALL = 5,
    CDMW_FULL_ARCHIVE_CANCELLED = 6,
};

typedef int (*cdmw_full_archive_progress_callback)(
    uint64_t completed,
    uint64_t total,
    const char* phase,
    const char* current_item,
    void* user_data);

CDMW_FULL_ARCHIVE_API uint32_t cdmw_full_archive_core_abi_version(void);

/*
 * Builds full_archive_index_v2 at index_path. Both paths are UTF-8. The source
 * archive tree is opened read-only; only index_path and its sibling staging
 * file can be written.
 */
CDMW_FULL_ARCHIVE_API int cdmw_full_archive_build_index_utf8(
    const char* package_root,
    const char* index_path,
    uint64_t* entry_count,
    char* error_message,
    size_t error_message_capacity);

/*
 * Progress-aware index build. The callback receives bounded totals whenever
 * the current phase has one. Returning non-zero requests cooperative
 * cancellation; callbacks are invoked on the calling thread.
 */
CDMW_FULL_ARCHIVE_API int cdmw_full_archive_build_index_with_progress_utf8(
    const char* package_root,
    const char* index_path,
    uint64_t* entry_count,
    cdmw_full_archive_progress_callback progress_callback,
    void* progress_user_data,
    char* error_message,
    size_t error_message_capacity);

/*
 * Decodes one archive entry into a caller-owned buffer. Call first with a null
 * output buffer to obtain required_size. The PAZ and virtual paths are UTF-8.
 */
CDMW_FULL_ARCHIVE_API int cdmw_full_archive_decode_entry_utf8(
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
 * Context-aware decode used by full CDMW. pamt_path is needed only for
 * partial DDS reconstruction through the sibling meta/0.pathc table. Passing
 * an empty pamt path preserves the context-free behavior above.
 */
CDMW_FULL_ARCHIVE_API int cdmw_full_archive_decode_entry_with_context_utf8(
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
