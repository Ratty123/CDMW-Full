#pragma once
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace cdmw::archive {

// Shared by archive preparation and Preview Core, including old prepared files.
template<class Byte, class Decompress>
std::vector<Byte> decode_partial_static_mesh(
    const std::string& extension, const std::vector<Byte>& data,
    std::uint64_t original_size, Decompress decompress) {
    if (data.size() < 0x50 || (extension != ".pam" && extension != ".pamlod")) return {};
    const auto read32 = [&data](size_t offset) {
        if (offset > data.size() || data.size() - offset < 4) throw std::runtime_error("Partial static mesh descriptor is truncated");
        std::uint32_t value = 0;
        for (size_t i = 0; i < 4; ++i) value |= static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + i])) << (8 * i);
        return value;
    };
    const auto write32 = [](std::vector<Byte>& bytes, size_t offset, std::uint32_t value) {
        for (size_t i = 0; i < 4; ++i) bytes[offset + i] = static_cast<Byte>((value >> (8 * i)) & 0xff);
    };
    if (original_size > 1024ull * 1024ull * 1024ull) throw std::runtime_error("Partial static mesh exceeds the one GiB resource limit");
    if (extension == ".pam") {
        if (data[0] != 'P' || data[1] != 'A' || data[2] != 'R' || data[3] != ' '
            || (read32(4) != 0x1802 && read32(4) != 0x01001806)) return {};
        const size_t offset = read32(0x3c), decoded_size = read32(0x40), compressed_size = read32(0x44);
        if (compressed_size == 0) return {};
        if (offset < 0x50 || offset > data.size() || compressed_size > data.size() - offset
            || decoded_size == 0 || data.size() - compressed_size + decoded_size != original_size) {
            throw std::runtime_error("Partial PAM geometry block has inconsistent sizes");
        }
        const auto begin = data.begin() + offset, end = begin + compressed_size;
        auto geometry = decompress(std::vector<Byte>(begin, end), decoded_size);
        if (geometry.size() != decoded_size) throw std::runtime_error("Partial PAM geometry block decompressed to an unexpected size");
        std::vector<Byte> result(data.begin(), begin);
        write32(result, 0x44, 0);
        result.insert(result.end(), geometry.begin(), geometry.end());
        result.insert(result.end(), end, data.end());
        return result;
    }
    const size_t lod_count = read32(0), geometry_offset = read32(4);
    if (lod_count == 0 || lod_count > 32) return {};
    if (geometry_offset < 0x50 + lod_count * 12 || geometry_offset > data.size()) throw std::runtime_error("Partial PAMLOD geometry table is invalid");
    // The descriptor table ends before the geometry's 16-byte alignment pad.
    // Its first block always starts at geometry_offset, which identifies the
    // table without guessing a mesh count or changing the metadata prefix.
    size_t table = 0;
    size_t table_matches = 0;
    for (size_t padding = 0; padding < 16; padding += 4) {
        if (geometry_offset < 0x50 + lod_count * 12 + padding) continue;
        const size_t candidate = geometry_offset - lod_count * 12 - padding;
        if (read32(candidate) == geometry_offset) { table = candidate; ++table_matches; }
    }
    if (table_matches != 1) throw std::runtime_error("Partial PAMLOD geometry table is invalid or ambiguous");
    struct Block { size_t offset; size_t decoded; size_t compressed; size_t destination; };
    std::vector<Block> blocks;
    size_t source_end = geometry_offset;
    std::uint64_t decoded_end = geometry_offset;
    bool compressed = false;
    for (size_t i = 0; i < lod_count; ++i) {
        const size_t offset = read32(table + i * 12), decoded_size = read32(table + i * 12 + 4), compressed_size = read32(table + i * 12 + 8);
        const size_t stored_size = compressed_size ? compressed_size : decoded_size;
        if (i != 0) {
            source_end = (source_end + 15) & ~size_t{15};
            decoded_end = (decoded_end + 15) & ~std::uint64_t{15};
        }
        if (offset != source_end || offset > data.size() || stored_size > data.size() - offset
            || decoded_size == 0 || decoded_end + decoded_size > original_size) {
            throw std::runtime_error("Partial PAMLOD geometry block has inconsistent sizes or offsets");
        }
        blocks.push_back({offset, decoded_size, compressed_size, static_cast<size_t>(decoded_end)});
        source_end = offset + stored_size;
        decoded_end += decoded_size;
        compressed = compressed || compressed_size != 0;
    }
    if (!compressed) return {};
    if (source_end != data.size() || decoded_end != original_size) throw std::runtime_error("Partial PAMLOD geometry blocks do not match the archive size");
    std::vector<Byte> result(data.begin(), data.begin() + geometry_offset);
    result.reserve(static_cast<size_t>(original_size));
    for (size_t i = 0; i < blocks.size(); ++i) {
        const auto& block = blocks[i];
        const auto begin = data.begin() + block.offset;
        std::vector<Byte> geometry(begin, begin + (block.compressed ? block.compressed : block.decoded));
        if (block.compressed) geometry = decompress(geometry, block.decoded);
        if (geometry.size() != block.decoded) throw std::runtime_error("Partial PAMLOD geometry block decompressed to an unexpected size");
        result.resize(block.destination, Byte{});
        write32(result, table + i * 12, static_cast<std::uint32_t>(block.destination));
        write32(result, table + i * 12 + 8, 0);
        result.insert(result.end(), geometry.begin(), geometry.end());
    }
    return result;
}

} // namespace cdmw::archive
