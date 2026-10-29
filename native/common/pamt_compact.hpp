#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

// Read-only support for the compact-name PAMT layout shipped in October 2026.
// The extension trailer selects this layout; legacy tables have no trailer.
namespace cdmw::archive {

template<class Bytes>
std::vector<std::string> pamt_extensions(const Bytes& data, size_t end) {
    if (end == data.size()) return {};
    if (end > data.size() || data.size() - end < 5) throw std::runtime_error("PAMT extension table is truncated");
    std::uint32_t length = 0;
    for (unsigned i = 0; i < 4; ++i) length |= static_cast<std::uint32_t>(static_cast<unsigned char>(data[end + i])) << (i * 8);
    end += 4;
    if (length != data.size() - end || data[end] != 0 || data.back() != 0) {
        throw std::runtime_error("PAMT extension table has invalid bounds or terminators");
    }
    std::vector<std::string> extensions;
    std::string current;
    for (; end < data.size(); ++end) {
        const auto ch = static_cast<unsigned char>(data[end]);
        if (ch == 0) {
            if (!extensions.empty() && (current.empty() || current[0] != '.' || current.find_first_of("/\\") != std::string::npos)) {
                throw std::runtime_error("PAMT extension table contains an invalid extension");
            }
            extensions.push_back(current);
            current.clear();
        } else {
            if (ch > 127) throw std::runtime_error("PAMT extension is not ASCII");
            current += static_cast<char>(ch);
        }
    }
    if (extensions.size() > 256) throw std::runtime_error("PAMT has too many extensions");
    return extensions;
}

inline std::string pamt_extension(const std::vector<std::string>& extensions, std::uint32_t flags) {
    if (extensions.empty()) return {};
    const auto index = flags >> 8;
    if (index >= extensions.size()) throw std::runtime_error("PAMT entry has an invalid extension index");
    return extensions[index];
}

struct CompactNamePart {
    std::uint32_t parent;
    std::string text;
};

template<class Bytes>
CompactNamePart compact_name_part(const Bytes& data, std::uint32_t offset) {
    size_t pos = offset;
    std::uint64_t distance = 0;
    bool terminated = false;
    for (unsigned shift = 0; shift < 35; shift += 7) {
        if (pos >= data.size()) throw std::runtime_error("Compact VFS parent distance is truncated");
        const auto value = static_cast<unsigned char>(data[pos++]);
        distance |= static_cast<std::uint64_t>(value & 0x7F) << shift;
        if (value < 0x80) { terminated = true; break; }
    }
    if (!terminated) throw std::runtime_error("Compact VFS parent distance is too large");
    if (distance > offset) throw std::runtime_error("Compact VFS parent precedes the name block");
    if (pos >= data.size()) throw std::runtime_error("Compact VFS text length is truncated");
    const auto length = static_cast<size_t>(static_cast<unsigned char>(data[pos++]));
    if (length > data.size() - pos) throw std::runtime_error("Compact VFS text is truncated");
    return {distance ? offset - static_cast<std::uint32_t>(distance) : 0xFFFFFFFFu,
        std::string(reinterpret_cast<const char*>(data.data() + pos), length)};
}

}  // namespace cdmw::archive
