// pathc_format.parse_pathc / encode_pathc.
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {
constexpr std::size_t head_size = 28;  // <QIIIII
constexpr std::size_t entry_size = 20;  // <HBB16s
constexpr std::size_t collision_size = 24;  // <IHH16s

// a * b + c without wrapping; saturates so an impossible size never matches a buffer.
std::uint64_t grow(std::uint64_t total, std::uint64_t count, std::uint64_t size) {
    if (size && count > (UINT64_MAX - total) / size) return UINT64_MAX;
    return total + count * size;
}
}  // namespace

PathcTable parse_pathc(const Bytes& data) {
    if (data.size() < head_size) throw FormatError("buffer is too short for a PATHC head");
    PathcTable table;
    table.reserved = u64(data, 0);
    table.header_size = u32(data, 8);
    const std::uint64_t headers = u32(data, 12), entries = u32(data, 16), collisions = u32(data, 20), filenames = u32(data, 24);
    std::uint64_t expected = head_size;
    expected = grow(expected, headers, table.header_size);
    expected = grow(expected, entries, 4 + entry_size);
    expected = grow(expected, collisions, collision_size);
    expected = grow(expected, filenames, 1);
    if (expected != data.size())
        throw FormatError("PATHC counts describe " + std::to_string(expected) + " bytes but the buffer holds " + std::to_string(data.size()));
    // Zero-byte headers occupy no bytes, so the size check cannot bound their count.
    if (table.header_size == 0 && headers > 0xFFFF) throw Unsupported("PATHC declares more empty headers than an entry can address");
    std::size_t at = head_size;
    for (std::uint64_t i = 0; i < headers; ++i, at += table.header_size) table.headers.push_back(slice(data, at, at + table.header_size));
    const std::size_t checksums = at;
    at += static_cast<std::size_t>(4 * entries);
    for (std::uint64_t i = 0; i < entries; ++i, at += entry_size) {
        PathcEntry entry;
        entry.checksum = u32(data, static_cast<std::size_t>(checksums + 4 * i));
        entry.header_index = u16(data, at);
        entry.collision_start = data[at + 2];
        entry.collision_end = data[at + 3];
        entry.block_infos = slice(data, at + 4, at + entry_size);
        table.entries.push_back(std::move(entry));
    }
    for (std::uint64_t i = 0; i < collisions; ++i, at += collision_size) table.collisions.push_back(slice(data, at, at + collision_size));
    table.filenames = slice(data, at, at + static_cast<std::size_t>(filenames));
    return table;
}

Bytes encode_pathc(const PathcTable& table) {
    for (const auto& header : table.headers)
        if (header.size() != table.header_size) throw FormatError("every texture header must be header_size bytes");
    Bytes out;
    put_u64(out, table.reserved);
    put_u32(out, table.header_size);
    put_u32(out, static_cast<std::uint32_t>(table.headers.size()));
    put_u32(out, static_cast<std::uint32_t>(table.entries.size()));
    put_u32(out, static_cast<std::uint32_t>(table.collisions.size()));
    put_u32(out, static_cast<std::uint32_t>(table.filenames.size()));
    for (const auto& header : table.headers) append(out, header);
    for (const auto& entry : table.entries) put_u32(out, entry.checksum);
    for (const auto& entry : table.entries) {
        if (entry.block_infos.size() != 16) throw FormatError("block infos are 16 bytes");
        // struct.pack('<H') refuses an index past 0xFFFF.
        if (entry.header_index > 0xFFFF) throw FormatError("ushort format requires 0 <= number <= 65535");
        put_u16(out, static_cast<std::uint16_t>(entry.header_index));
        out.push_back(entry.collision_start);
        out.push_back(entry.collision_end);
        append(out, entry.block_infos);
    }
    for (const auto& row : table.collisions) {
        if (row.size() != collision_size) throw FormatError("collision rows are 24 bytes");
        append(out, row);
    }
    append(out, table.filenames);
    return out;
}

}  // namespace cdmw::compose::detail
