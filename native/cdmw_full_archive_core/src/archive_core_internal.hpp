#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <functional>
#include <fstream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <numeric>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace cdmw::full_archive {

namespace fs = std::filesystem;

constexpr std::uint64_t kMaximumPamtBytes = 512ull * 1024ull * 1024ull;
constexpr std::uint64_t kMaximumDecodedEntryBytes = 1024ull * 1024ull * 1024ull;
constexpr std::uint32_t kIndexRecordSize = 80;

struct EntrySource {
    fs::path pamt_path;
    std::vector<fs::path> paz_paths;
};

struct Entry {
    std::string path;
    std::shared_ptr<const EntrySource> source;
    std::uint64_t archive_offset = 0;
    std::uint64_t stored_size = 0;
    std::uint64_t original_size = 0;
    std::uint32_t flags = 0;
    std::uint32_t paz_index = 0;
};

struct DecodeResult {
    std::vector<std::uint8_t> bytes;
    std::string note;
};

class UnsupportedError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class CancelledError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

using ProgressSink = std::function<void(
    std::uint64_t,
    std::uint64_t,
    const std::string&,
    const std::string&)>;

std::vector<Entry> scan_package_root(const fs::path& package_root, const ProgressSink& progress = {});
void write_index_atomic(
    const fs::path& index_path,
    const std::vector<Entry>& entries,
    const ProgressSink& progress = {});
DecodeResult decode_entry(
    const std::string& virtual_path,
    const fs::path& pamt_path,
    const fs::path& paz_path,
    std::uint64_t archive_offset,
    std::uint64_t stored_size,
    std::uint64_t original_size,
    std::uint32_t flags);

std::vector<std::uint8_t> reconstruct_partial_dds(
    const std::string& virtual_path,
    const fs::path& pamt_path,
    const std::vector<std::uint8_t>& payload,
    std::uint64_t original_size);

std::uint32_t calculate_pa_checksum(const std::string& value);

std::vector<std::uint8_t> crypt_chacha20_filename(
    const std::vector<std::uint8_t>& data,
    const std::string& filename);

inline std::uint16_t read_u16(const std::vector<std::uint8_t>& data, size_t offset) {
    if (offset > data.size() || data.size() - offset < 2) {
        throw std::runtime_error("archive field is truncated");
    }
    return static_cast<std::uint16_t>(data[offset]) |
        static_cast<std::uint16_t>(data[offset + 1] << 8);
}

inline std::uint32_t read_u32(const std::vector<std::uint8_t>& data, size_t offset) {
    if (offset > data.size() || data.size() - offset < 4) {
        throw std::runtime_error("archive field is truncated");
    }
    return static_cast<std::uint32_t>(data[offset]) |
        (static_cast<std::uint32_t>(data[offset + 1]) << 8) |
        (static_cast<std::uint32_t>(data[offset + 2]) << 16) |
        (static_cast<std::uint32_t>(data[offset + 3]) << 24);
}

inline void append_u32(std::vector<std::uint8_t>& out, std::uint32_t value) {
    for (int shift = 0; shift < 32; shift += 8) {
        out.push_back(static_cast<std::uint8_t>((value >> shift) & 0xFFu));
    }
}

inline void append_u64(std::vector<std::uint8_t>& out, std::uint64_t value) {
    for (int shift = 0; shift < 64; shift += 8) {
        out.push_back(static_cast<std::uint8_t>((value >> shift) & 0xFFu));
    }
}

inline std::vector<std::uint8_t> read_binary(const fs::path& path, std::uint64_t maximum_bytes) {
    std::error_code error;
    const auto size = fs::file_size(path, error);
    if (error) {
        throw std::runtime_error("could not determine file size for " + path.string());
    }
    if (size > maximum_bytes || size > static_cast<std::uint64_t>(std::numeric_limits<size_t>::max())) {
        throw std::runtime_error("file exceeds the read-only resource limit: " + path.string());
    }
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw std::runtime_error("could not open " + path.string());
    }
    std::vector<std::uint8_t> data(static_cast<size_t>(size));
    if (!data.empty()) {
        stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(stream.gcount()) != data.size()) {
            throw std::runtime_error("short read from " + path.string());
        }
    }
    return data;
}

inline std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

// The C locale is never replaced in this library, so folding only A-Z matches
// std::tolower exactly while staying branch-predictable in the index sort.
inline unsigned char ascii_lower(unsigned char value) {
    return value >= 'A' && value <= 'Z' ? static_cast<unsigned char>(value + ('a' - 'A')) : value;
}

inline int compare_case_insensitive(std::string_view left, std::string_view right) {
    const auto common_size = std::min(left.size(), right.size());
    for (size_t index = 0; index < common_size; ++index) {
        const auto left_raw = static_cast<unsigned char>(left[index]);
        const auto right_raw = static_cast<unsigned char>(right[index]);
        if (left_raw == right_raw) continue;
        const auto left_lower = ascii_lower(left_raw);
        const auto right_lower = ascii_lower(right_raw);
        if (left_lower < right_lower) return -1;
        if (left_lower > right_lower) return 1;
    }
    if (left.size() < right.size()) return -1;
    if (left.size() > right.size()) return 1;
    return 0;
}

inline std::string slash_copy(std::string value) {
    std::replace(value.begin(), value.end(), '\\', '/');
    while (!value.empty() && value.front() == '/') value.erase(value.begin());
    while (!value.empty() && value.back() == '/') value.pop_back();
    return value;
}

inline std::string basename_from_path(const std::string& path) {
    const auto position = path.find_last_of("/\\");
    return position == std::string::npos ? path : path.substr(position + 1);
}

inline fs::path utf8_path(const char* value) {
    if (value == nullptr || *value == '\0') {
        throw std::invalid_argument("path must not be empty");
    }
    return fs::u8path(value);
}

}  // namespace cdmw::full_archive
