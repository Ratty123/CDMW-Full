#include "archive_core_internal.hpp"

namespace cdmw::archive {

namespace {

constexpr size_t kMaximumPathcCacheEntries = 8;
constexpr std::uint32_t kMaximumTextureDimension = 32768;

std::uint32_t rotate32(std::uint32_t value, int shift) {
    return static_cast<std::uint32_t>((value << shift) | (value >> (32 - shift)));
}

std::uint32_t read_padded_u32(const std::string& value, size_t offset) {
    std::uint32_t output = 0;
    for (size_t index = 0; index < 4; ++index) {
        if (offset + index < value.size()) {
            output |= static_cast<std::uint32_t>(static_cast<unsigned char>(value[offset + index])) << (index * 8);
        }
    }
    return output;
}

std::vector<std::uint8_t> lz4_decompress_block(
    const std::vector<std::uint8_t>& input,
    size_t output_size) {
    if (output_size > kMaximumDecodedEntryBytes) throw std::runtime_error("partial DDS block exceeds the resource limit");
    std::vector<std::uint8_t> output(output_size);
    size_t input_position = 0;
    size_t output_position = 0;
    while (input_position < input.size()) {
        const auto token = input[input_position++];
        size_t literal_length = token >> 4;
        if (literal_length == 15) {
            std::uint8_t value = 255;
            while (input_position < input.size() && value == 255) {
                value = input[input_position++];
                literal_length += value;
            }
        }
        if (literal_length > input.size() - input_position || literal_length > output.size() - output_position) {
            throw std::runtime_error("partial DDS LZ4 literal run is outside its buffer");
        }
        std::copy_n(input.data() + input_position, literal_length, output.data() + output_position);
        input_position += literal_length;
        output_position += literal_length;
        if (input_position == input.size()) break;
        if (input.size() - input_position < 2) throw std::runtime_error("partial DDS LZ4 match offset is truncated");
        const size_t match_offset = input[input_position] | (static_cast<size_t>(input[input_position + 1]) << 8);
        input_position += 2;
        if (match_offset == 0 || match_offset > output_position) throw std::runtime_error("partial DDS LZ4 match offset is invalid");
        size_t match_length = token & 0x0Fu;
        if (match_length == 15) {
            std::uint8_t value = 255;
            while (input_position < input.size() && value == 255) {
                value = input[input_position++];
                match_length += value;
            }
        }
        match_length += 4;
        if (match_length > output.size() - output_position) throw std::runtime_error("partial DDS LZ4 match run is outside its output buffer");
        for (size_t index = 0; index < match_length; ++index) {
            output[output_position + index] = output[output_position - match_offset + index];
        }
        output_position += match_length;
    }
    if (output_position != output.size()) throw std::runtime_error("partial DDS LZ4 block decoded to an unexpected size");
    return output;
}

std::vector<std::uint32_t> u32_values(const std::vector<std::uint8_t>& data, size_t offset, size_t count) {
    std::vector<std::uint32_t> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) values.push_back(read_u32(data, offset + index * 4));
    return values;
}

int dds_bytes_per_block(std::uint32_t dxgi_format, const std::string& fourcc) {
    static const std::set<std::uint32_t> block8_formats = {71u, 72u, 80u, 81u};
    static const std::set<std::uint32_t> block16_formats = {74u, 75u, 77u, 78u, 83u, 84u, 94u, 95u, 96u, 98u, 99u};
    if (block8_formats.count(dxgi_format) != 0) return 8;
    if (block16_formats.count(dxgi_format) != 0) return 16;
    const auto code = lower_copy(fourcc);
    if (code == "dxt1" || code == "bc4u" || code == "bc4s" || code == "ati1") return 8;
    if (code == "dxt3" || code == "dxt5" || code == "bc5u" || code == "bc5s" || code == "ati2" || code == "rxgb") return 16;
    return 0;
}

size_t dds_surface_size(
    int width,
    int height,
    std::uint32_t dxgi_format,
    const std::string& fourcc,
    std::uint32_t pixel_flags,
    std::uint32_t rgb_bit_count,
    std::uint32_t pitch_or_linear_size,
    int mip_level) {
    if (width <= 0 || height <= 0) return 0;
    const int bytes_per_block = dds_bytes_per_block(dxgi_format, fourcc);
    if (bytes_per_block > 0) {
        const int block_width = std::max(1, (width + 3) / 4);
        const int block_height = std::max(1, (height + 3) / 4);
        return static_cast<size_t>(block_width) * static_cast<size_t>(block_height) * static_cast<size_t>(bytes_per_block);
    }
    constexpr std::uint32_t kRawPixelFlags = 0x1u | 0x2u | 0x40u | 0x20000u;
    if ((pixel_flags & kRawPixelFlags) != 0 && rgb_bit_count > 0 && rgb_bit_count % 8u == 0) {
        return static_cast<size_t>(width) * static_cast<size_t>(height) * static_cast<size_t>(rgb_bit_count / 8u);
    }
    if (pitch_or_linear_size > 0) {
        const auto pitch = std::max<std::uint32_t>(1u, pitch_or_linear_size >> std::max(0, mip_level));
        return static_cast<size_t>(pitch) * static_cast<size_t>(height);
    }
    throw UnsupportedError("unsupported partial DDS pixel format");
}

struct PathcEntry {
    std::uint16_t texture_header_index = 0;
    std::vector<std::uint8_t> compressed_block_infos;
};

struct PathcCollisionEntry {
    std::uint32_t filename_offset = 0;
    std::uint16_t texture_header_index = 0;
    std::vector<std::uint8_t> compressed_block_infos;
};

struct PathcCollection {
    std::uint32_t header_size = 0;
    std::vector<std::vector<std::uint8_t>> headers;
    std::unordered_map<std::uint32_t, PathcEntry> entries;
    std::unordered_map<std::string, PathcCollisionEntry> collisions;

    std::vector<std::uint8_t> get_header(const std::string& raw_path) const {
        const auto normalized = slash_copy(raw_path);
        const auto found = entries.find(calculate_pa_checksum("/" + normalized));
        if (found == entries.end()) throw std::runtime_error("partial DDS PATHC entry was not found for " + raw_path);

        const PathcEntry* direct = &found->second;
        std::uint16_t header_index = direct->texture_header_index;
        const std::vector<std::uint8_t>* block_infos = &direct->compressed_block_infos;
        if (header_index == 0xFFFFu) {
            const auto collision = collisions.find(normalized);
            if (collision == collisions.end()) throw std::runtime_error("partial DDS PATHC collision entry was not found for " + raw_path);
            header_index = collision->second.texture_header_index;
            block_infos = &collision->second.compressed_block_infos;
        }
        if (header_index >= headers.size()) throw std::runtime_error("partial DDS PATHC header index is outside the header table");

        auto header = headers[header_index];
        if (header_size == 0x94u && header.size() >= 0x94u && block_infos->size() >= 16u) {
            std::copy_n(block_infos->begin(), 16, header.begin() + 0x20);
        }
        return header;
    }
};

PathcCollection load_pathc(const fs::path& path) {
    const auto raw = read_binary(path, kMaximumPamtBytes);
    if (raw.size() < 28) throw std::runtime_error("PATHC file is too small");
    PathcCollection collection;
    collection.header_size = read_u32(raw, 8);
    const auto header_count = read_u32(raw, 12);
    const auto entry_count = read_u32(raw, 16);
    const auto collision_count = read_u32(raw, 20);
    const auto filenames_length = read_u32(raw, 24);
    if (collection.header_size < 0x80u || collection.header_size > 4096u) throw std::runtime_error("PATHC header size is unsupported");
    size_t offset = 28;
    auto require_bytes = [&](size_t count, const char* message) {
        if (count > raw.size() - std::min(raw.size(), offset)) throw std::runtime_error(message);
    };

    collection.headers.reserve(header_count);
    for (std::uint32_t index = 0; index < header_count; ++index) {
        require_bytes(collection.header_size, "PATHC texture header table is truncated");
        collection.headers.emplace_back(raw.begin() + offset, raw.begin() + offset + collection.header_size);
        offset += collection.header_size;
    }

    std::vector<std::uint32_t> checksums;
    checksums.reserve(entry_count);
    for (std::uint32_t index = 0; index < entry_count; ++index) {
        require_bytes(4, "PATHC checksum table is truncated");
        checksums.push_back(read_u32(raw, offset));
        offset += 4;
    }
    for (std::uint32_t index = 0; index < entry_count; ++index) {
        require_bytes(20, "PATHC entry table is truncated");
        PathcEntry entry;
        entry.texture_header_index = read_u16(raw, offset);
        entry.compressed_block_infos.assign(raw.begin() + offset + 4, raw.begin() + offset + 20);
        collection.entries[checksums[index]] = std::move(entry);
        offset += 20;
    }

    std::vector<PathcCollisionEntry> collision_rows;
    collision_rows.reserve(collision_count);
    for (std::uint32_t index = 0; index < collision_count; ++index) {
        require_bytes(24, "PATHC collision table is truncated");
        PathcCollisionEntry collision;
        collision.filename_offset = read_u32(raw, offset);
        collision.texture_header_index = read_u16(raw, offset + 4);
        collision.compressed_block_infos.assign(raw.begin() + offset + 8, raw.begin() + offset + 24);
        collision_rows.push_back(std::move(collision));
        offset += 24;
    }
    require_bytes(filenames_length, "PATHC filename table is truncated");
    for (auto& collision : collision_rows) {
        if (collision.filename_offset >= filenames_length) continue;
        const size_t start = offset + collision.filename_offset;
        size_t end = start;
        while (end < offset + filenames_length && raw[end] != 0) ++end;
        const auto path_value = slash_copy(std::string(
            reinterpret_cast<const char*>(raw.data() + start),
            end - start));
        if (!path_value.empty()) collection.collisions[path_value] = std::move(collision);
    }
    return collection;
}

std::vector<std::uint8_t> cached_pathc_header(const fs::path& pamt_path, const std::string& virtual_path) {
    const auto pathc_path = pamt_path.parent_path().parent_path() / "meta" / "0.pathc";
    std::error_code error;
    const auto size = fs::file_size(pathc_path, error);
    if (error) throw std::runtime_error("partial DDS metadata was not found: " + pathc_path.string());
    const auto write_time = fs::last_write_time(pathc_path, error);
    if (error) throw std::runtime_error("could not inspect PATHC timestamp: " + pathc_path.string());

    struct CacheValue {
        std::uintmax_t size;
        fs::file_time_type write_time;
        PathcCollection collection;
    };
    static std::mutex cache_mutex;
    static std::map<std::string, CacheValue> cache;
    std::lock_guard<std::mutex> guard(cache_mutex);
    const auto key = fs::absolute(pathc_path).lexically_normal().string();
    auto found = cache.find(key);
    if (found == cache.end() || found->second.size != size || found->second.write_time != write_time) {
        if (found == cache.end() && cache.size() >= kMaximumPathcCacheEntries) cache.erase(cache.begin());
        auto loaded = load_pathc(pathc_path);
        found = cache.insert_or_assign(key, CacheValue{size, write_time, std::move(loaded)}).first;
    }
    return found->second.collection.get_header(virtual_path);
}

}  // namespace

std::uint32_t calculate_pa_checksum(const std::string& value) {
    const auto length = static_cast<std::uint32_t>(value.size());
    std::uint32_t remaining = length;
    std::uint32_t a = length + 0xDEBA1DCDu;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    while (remaining > 12) {
        a += read_padded_u32(value, offset);
        b += read_padded_u32(value, offset + 4);
        c += read_padded_u32(value, offset + 8);
        a -= c; a ^= rotate32(c, 4); c += b;
        b -= a; b ^= rotate32(a, 6); a += c;
        c -= b; c ^= rotate32(b, 8); b += a;
        a -= c; a ^= rotate32(c, 16); c += b;
        b -= a; b ^= rotate32(a, 19); a += c;
        c -= b; c ^= rotate32(b, 4); b += a;
        offset += 12;
        remaining -= 12;
    }
    if (remaining == 0) return c;
    a += read_padded_u32(value, offset);
    b += read_padded_u32(value, offset + 4);
    c += read_padded_u32(value, offset + 8);
    c = (c ^ b) - rotate32(b, 14);
    a = (a ^ c) - rotate32(c, 11);
    b = (b ^ a) - rotate32(a, 25);
    c = (c ^ b) - rotate32(b, 16);
    a = (a ^ c) - rotate32(c, 4);
    b = (b ^ a) - rotate32(a, 14);
    return (c ^ b) - rotate32(b, 24);
}

std::vector<std::uint8_t> reconstruct_partial_dds(
    const std::string& virtual_path,
    const fs::path& pamt_path,
    const std::vector<std::uint8_t>& payload,
    std::uint64_t original_size) {
    auto header = cached_pathc_header(pamt_path, virtual_path);
    if (header.size() < 0x80u || std::memcmp(header.data(), "DDS ", 4) != 0 || read_u32(header, 4) != 124u) {
        throw std::runtime_error("partial DDS PATHC header is missing or invalid");
    }
    const auto height = read_u32(header, 12);
    const auto width = read_u32(header, 16);
    const auto pitch_or_linear_size = read_u32(header, 20);
    const auto depth = read_u32(header, 24);
    const auto mip_map_count = std::max<std::uint32_t>(1u, read_u32(header, 28));
    if (width == 0 || height == 0 || width > kMaximumTextureDimension || height > kMaximumTextureDimension || depth > kMaximumTextureDimension) {
        throw std::runtime_error("partial DDS dimensions exceed the resource limit");
    }
    const auto reserved = u32_values(header, 32, 11);
    const auto pixel_flags = read_u32(header, 80);
    const std::string fourcc(reinterpret_cast<const char*>(header.data() + 84), 4);
    const auto rgb_bit_count = read_u32(header, 88);
    const auto caps2 = read_u32(header, 112);
    const bool is_dx10 = fourcc == "DX10";
    const size_t header_size = is_dx10 ? 0x94u : 0x80u;
    if (header.size() < header_size || payload.size() < header_size) throw std::runtime_error("partial DDS header is truncated");
    const auto dxgi_format = is_dx10 ? read_u32(header, 0x80) : 0u;
    const auto array_size = is_dx10 ? read_u32(header, 0x8C) : 1u;
    const bool single_chunk = (is_dx10 && array_size >= 2u) || mip_map_count <= 5u || caps2 != 0u || depth >= 2u;

    std::vector<std::uint32_t> compressed_sizes;
    std::vector<size_t> decoded_sizes;
    if (single_chunk) {
        compressed_sizes.push_back(reserved[0]);
        decoded_sizes.push_back(reserved[1]);
    } else {
        compressed_sizes.assign(reserved.begin(), reserved.begin() + 4);
        int current_width = static_cast<int>(width);
        int current_height = static_cast<int>(height);
        const int levels = static_cast<int>(std::min<std::uint32_t>(4u, mip_map_count));
        for (int level = 0; level < levels; ++level) {
            decoded_sizes.push_back(dds_surface_size(
                current_width,
                current_height,
                dxgi_format,
                fourcc,
                pixel_flags,
                rgb_bit_count,
                pitch_or_linear_size,
                level));
            current_width = std::max(1, current_width >> 1);
            current_height = std::max(1, current_height >> 1);
        }
    }

    if (std::memcmp(payload.data(), "DDS ", 4) == 0) {
        const auto payload_reserved = u32_values(payload, 32, 11);
        std::vector<std::uint32_t> payload_compressed;
        std::vector<size_t> payload_decoded = decoded_sizes;
        if (single_chunk) {
            payload_compressed.push_back(payload_reserved[0]);
            payload_decoded = {payload_reserved[1]};
        } else {
            payload_compressed.assign(payload_reserved.begin(), payload_reserved.begin() + compressed_sizes.size());
        }
        const auto sum_u64 = [](const auto& values) {
            std::uint64_t total = 0;
            for (const auto value : values) total += static_cast<std::uint64_t>(value);
            return total;
        };
        const auto payload_bytes = sum_u64(payload_compressed);
        const auto payload_decoded_bytes = sum_u64(payload_decoded);
        const auto current_bytes = sum_u64(compressed_sizes);
        if (payload_bytes > 0 && payload_bytes <= payload_decoded_bytes &&
            payload_bytes <= payload.size() - header_size &&
            (current_bytes == 0 || current_bytes > payload.size() - header_size || payload_bytes < current_bytes)) {
            compressed_sizes = std::move(payload_compressed);
            if (single_chunk) decoded_sizes = std::move(payload_decoded);
        }
    }

    std::vector<std::uint8_t> output;
    output.reserve(static_cast<size_t>(std::min<std::uint64_t>(original_size, kMaximumDecodedEntryBytes)));
    output.insert(output.end(), header.begin(), header.begin() + header_size);
    size_t source_offset = header_size;
    const size_t block_count = std::min(compressed_sizes.size(), decoded_sizes.size());
    for (size_t index = 0; index < block_count; ++index) {
        const auto compressed_size = compressed_sizes[index];
        const auto decoded_size = decoded_sizes[index];
        if (compressed_size == 0 || decoded_size == 0) continue;
        if (compressed_size > payload.size() - source_offset) throw std::runtime_error("partial DDS block is truncated");
        std::vector<std::uint8_t> block(payload.begin() + source_offset, payload.begin() + source_offset + compressed_size);
        if (compressed_size != decoded_size) block = lz4_decompress_block(block, decoded_size);
        if (block.size() > kMaximumDecodedEntryBytes - output.size()) throw std::runtime_error("partial DDS exceeds the decoded resource limit");
        output.insert(output.end(), block.begin(), block.end());
        source_offset += compressed_size;
    }
    if (source_offset < payload.size()) {
        if (payload.size() - source_offset > kMaximumDecodedEntryBytes - output.size()) throw std::runtime_error("partial DDS exceeds the decoded resource limit");
        output.insert(output.end(), payload.begin() + source_offset, payload.end());
    }
    return output;
}

}  // namespace cdmw::archive
