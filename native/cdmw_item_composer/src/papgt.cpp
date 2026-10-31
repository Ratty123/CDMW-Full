// papgt_format.parse_papgt / serialize_papgt / papgt_with_directory.
#include "composer_internal.hpp"

namespace cdmw::compose {
using namespace detail;
namespace {
constexpr std::size_t header_bytes = 12;
constexpr std::size_t record_bytes = 12;

bool ascii(const std::string& text) {
    return std::all_of(text.begin(), text.end(), [](char c) { return static_cast<unsigned char>(c) < 0x80; });
}

std::string lowered(std::string text) {
    for (auto& c : text) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return text;
}
}  // namespace

std::vector<PapgtDirectory> parse_papgt(const Bytes& data) {
    if (data.size() < header_bytes + 4) throw FormatError("PAPGT is too small to hold a header");
    if (u32(data, 4) != pa_checksum(data.data() + header_bytes, data.size() - header_bytes))
        throw FormatError("PAPGT checksum does not match its body");
    const std::size_t count = data[8];
    const std::size_t size_at = header_bytes + count * record_bytes;
    if (size_at + 4 > data.size()) throw FormatError("PAPGT directory count " + std::to_string(count) + " leaves no string table size");
    const std::uint64_t table_size = u32(data, size_at);
    if (size_at + 4 + table_size != data.size())
        throw FormatError("PAPGT does not end where the string table for " + std::to_string(count) + " directories says it should");
    const auto table = slice(data, size_at + 4, data.size());
    std::vector<PapgtDirectory> directories;
    for (std::size_t index = 0; index < count; ++index) {
        const auto at = header_bytes + index * record_bytes;
        const auto offset = u32(data, at + 4);
        if (offset >= table.size()) throw FormatError("PAPGT name offset is past the string table");
        const auto end = std::find(table.begin() + offset, table.end(), 0);
        if (end == table.end()) throw FormatError("PAPGT name is not terminated");
        std::string name(table.begin() + offset, end);
        if (!ascii(name)) throw FormatError("'ascii' codec can't decode a PAPGT name");
        directories.push_back({std::move(name), u32(data, at), u32(data, at + 8)});
    }
    return directories;
}

Bytes serialize_papgt(const std::vector<PapgtDirectory>& directories, const Bytes& header) {
    Bytes out = header.empty() ? Bytes(header_bytes) : slice(header, 0, header_bytes);
    if (out.size() != header_bytes) throw FormatError("a PAPGT header is twelve bytes");
    if (directories.size() > 0xFF) throw FormatError("a PAPGT header holds the directory count in one byte");
    // The count the game reads, in the low byte of the third field.
    out[8] = static_cast<std::uint8_t>(directories.size());
    Bytes table;
    std::map<std::string, std::uint32_t> offsets;
    for (const auto& directory : directories) {
        if (offsets.count(directory.name)) continue;
        if (!ascii(directory.name)) throw FormatError("'ascii' codec can't encode a PAPGT name");
        offsets.emplace(directory.name, static_cast<std::uint32_t>(table.size()));
        table.insert(table.end(), directory.name.begin(), directory.name.end());
        table.push_back(0);
    }
    Bytes body;
    for (const auto& directory : directories) {
        put_u32(body, directory.flags);
        put_u32(body, offsets.at(directory.name));
        put_u32(body, directory.pamt_checksum);
    }
    put_u32(body, static_cast<std::uint32_t>(table.size()));
    append(body, table);
    const auto checksum = pa_checksum(body.data(), body.size());
    for (std::size_t i = 0; i < 4; ++i) out[4 + i] = static_cast<std::uint8_t>(checksum >> (8 * i));
    append(out, body);
    return out;
}

namespace {
bool legacy_papgt(const Bytes& data) {
    try {
        parse_papgt(data);
    } catch (const FormatError&) {
        return false;
    }
    return true;
}
}  // namespace

bool is_compact_papgt(const Bytes& data) {
    if (legacy_papgt(data)) return false;
    try {
        read_papgt_directories(data);
    } catch (const FormatError&) {
        return false;
    }
    return true;
}

// papgt_format.read_papgt_directories: the October 2026 layout has a four-byte header
// (count in byte 2, version 2 in byte 3) and an opaque 64-byte trailer.
std::vector<PapgtDirectory> read_papgt_directories(const Bytes& data) {
    if (legacy_papgt(data)) return parse_papgt(data);
    if (data.size() < 4 || data[3] != 2) return parse_papgt(data);  // reports the legacy failure
    const std::size_t count = data[2];
    const std::size_t size_at = 4 + count * record_bytes;
    if (size_at + 4 + 64 > data.size()) throw FormatError("Compact PAPGT directory table is truncated");
    const std::uint64_t table_size = u32(data, size_at);
    if (size_at + 4 + table_size + 64 != data.size()) throw FormatError("Compact PAPGT string table or trailer has invalid bounds");
    const auto table = slice(data, size_at + 4, size_at + 4 + static_cast<std::size_t>(table_size));
    std::vector<PapgtDirectory> directories;
    std::set<std::string> seen;
    for (std::size_t index = 0; index < count; ++index) {
        const auto at = 4 + index * record_bytes;
        const auto offset = u32(data, at + 4);
        if (offset >= table.size()) throw FormatError("PAPGT name offset is past the string table");
        const auto end = std::find(table.begin() + offset, table.end(), 0);
        if (end == table.end()) throw FormatError("PAPGT name is not terminated");
        std::string name(table.begin() + offset, end);
        if (!ascii(name) || name.empty() || name == "." || name == ".." || name.find_first_of("/\\:") != std::string::npos ||
            !seen.insert(lowered(name)).second)
            throw FormatError("Compact PAPGT has an invalid or duplicate directory name");
        directories.push_back({std::move(name), u32(data, at), u32(data, at + 8)});
    }
    return directories;
}

Bytes papgt_with_directory(const Bytes& data, const std::string& name, std::uint32_t pamt_checksum, std::uint32_t flags, bool first) {
    // The game authenticates the compact list: a copy with one more directory fails to
    // load and the game then mounts nothing (game 2.04.02, 2026-10-31).
    if (is_compact_papgt(data))
        throw Unsupported("the game checks its archive mount list since the October 2026 update and will not start with a private archive group added");
    auto directories = parse_papgt(data);
    const auto existing = std::find_if(directories.begin(), directories.end(), [&](const PapgtDirectory& d) { return d.name == name; });
    if (existing != directories.end()) {
        existing->pamt_checksum = pamt_checksum;
    } else {
        directories.insert(first ? directories.begin() : directories.end(), PapgtDirectory{name, flags, pamt_checksum});
    }
    return serialize_papgt(directories, slice(data, 0, header_bytes));
}

}  // namespace cdmw::compose
