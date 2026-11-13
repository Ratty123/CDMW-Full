#pragma once

// Long paths for every native program that opens files (2026-11-13).
//
// Windows refuses a path longer than MAX_PATH (260 characters) unless it carries
// the extended-length prefix \\?\ or the machine has long paths switched on, which
// CDMW must not change. CDMW's own folders (a profile, a draft, a mod's output)
// can pass that length under a long user or profile name. Every native open,
// create, rename, remove and query therefore goes through cdmw::long_path(),
// which makes the path absolute and gives it the prefix. The prefix turns off
// Windows' own clean-up of the path, so the helper does that first: it
// normalizes it and uses backslashes only.
//
// Elsewhere it returns the path as given.

#include <filesystem>
#include <string>
#include <system_error>

namespace cdmw {

inline std::filesystem::path long_path(const std::filesystem::path& path) {
#ifdef _WIN32
    if (path.empty()) {
        return path;
    }
    // Backslashes first, so a prefix written with forward slashes (//?/C:/x) is
    // seen as one and not wrapped again as a UNC path.
    std::wstring given = path.native();
    for (wchar_t& character : given) {
        if (character == L'/') {
            character = L'\\';
        }
    }
    if (given.rfind(L"\\\\?\\", 0) == 0 || given.rfind(L"\\\\.\\", 0) == 0) {
        return std::filesystem::path(given);  // already extended-length, or a device
    }
    std::error_code error;
    std::filesystem::path absolute = std::filesystem::absolute(std::filesystem::path(given), error);
    if (error) {
        return path;
    }
    std::wstring text = absolute.lexically_normal().native();
    for (wchar_t& character : text) {
        if (character == L'/') {
            character = L'\\';
        }
    }
    if (text.rfind(L"\\\\", 0) == 0) {
        return std::filesystem::path(L"\\\\?\\UNC\\" + text.substr(2));  // \\server\share
    }
    return std::filesystem::path(L"\\\\?\\" + text);
#else
    return path;
#endif
}

}  // namespace cdmw
