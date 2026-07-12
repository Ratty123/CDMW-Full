
static std::vector<char> read_archive_ref_raw_bytes(const ArchiveEntryRef& entry) {
    if (entry.paz_file.empty()) {
        throw std::runtime_error("job has no paz_file");
    }
    if (entry.comp_size == 0) {
        return {};
    }
    std::ifstream in(entry.paz_file, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open PAZ file " + entry.paz_file.string());
    }
    in.seekg(0, std::ios::end);
    const auto end_pos = in.tellg();
    if (end_pos < 0) {
        throw std::runtime_error("could not determine PAZ file size");
    }
    const std::uint64_t file_size = static_cast<std::uint64_t>(end_pos);
    if (entry.offset > file_size || entry.comp_size > file_size || entry.offset + entry.comp_size > file_size) {
        throw std::runtime_error("archive entry byte range is outside the PAZ file");
    }
    in.seekg(static_cast<std::streamoff>(entry.offset), std::ios::beg);
    std::vector<char> data(static_cast<size_t>(entry.comp_size));
    if (!data.empty()) {
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) {
            throw std::runtime_error("short read from PAZ file");
        }
    }
    return data;
}

static std::vector<char> read_entry_raw_bytes(const EntryJob& job) {
    return read_archive_ref_raw_bytes(job.entry.path.empty() ? ArchiveEntryRef{
        job.path,
        basename_from_path(job.path),
        job.extension,
        fs::path(),
        job.paz_file,
        job.offset,
        job.comp_size,
        job.orig_size,
        job.flags,
        0,
    } : job.entry);
}

static std::vector<char> crypt_chacha20_filename(const std::vector<char>& data, const std::string& filename);

static std::vector<char> lz4_decompress_block(const std::vector<char>& input, size_t output_size) {
    std::vector<char> output(output_size);
    size_t ip = 0;
    size_t op = 0;
    while (ip < input.size()) {
        const unsigned char token = static_cast<unsigned char>(input[ip++]);
        size_t literal_len = token >> 4;
        if (literal_len == 15) {
            unsigned char s = 255;
            while (ip < input.size() && s == 255) {
                s = static_cast<unsigned char>(input[ip++]);
                literal_len += s;
            }
        }
        if (ip + literal_len > input.size() || op + literal_len > output.size()) {
            throw std::runtime_error("LZ4 literal run is outside buffer");
        }
        if (literal_len > 0) {
            std::memcpy(output.data() + op, input.data() + ip, literal_len);
            ip += literal_len;
            op += literal_len;
        }
        if (ip >= input.size()) break;
        if (ip + 2 > input.size()) throw std::runtime_error("LZ4 match offset is truncated");
        const size_t match_offset = static_cast<unsigned char>(input[ip]) | (static_cast<size_t>(static_cast<unsigned char>(input[ip + 1])) << 8);
        ip += 2;
        if (match_offset == 0 || match_offset > op) throw std::runtime_error("LZ4 match offset is invalid");
        size_t match_len = token & 0x0Fu;
        if (match_len == 15) {
            unsigned char s = 255;
            while (ip < input.size() && s == 255) {
                s = static_cast<unsigned char>(input[ip++]);
                match_len += s;
            }
        }
        match_len += 4;
        if (op + match_len > output.size()) throw std::runtime_error("LZ4 match run is outside output buffer");
        for (size_t i = 0; i < match_len; ++i) {
            output[op + i] = output[op - match_offset + i];
        }
        op += match_len;
    }
    if (op != output.size()) {
        output.resize(op);
    }
    return output;
}

static std::uint32_t pa_rot32(std::uint32_t value, int shift) {
    return static_cast<std::uint32_t>((value << shift) | (value >> (32 - shift)));
}

static std::uint32_t calculate_pa_checksum(const std::string& value) {
    const std::string data = value;
    std::uint32_t length = static_cast<std::uint32_t>(data.size());
    std::uint32_t remaining = length;
    std::uint32_t a = length + 0xDEBA1DCDu;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    auto read_tail_u32 = [&](size_t local_offset) -> std::uint32_t {
        std::uint32_t out = 0;
        for (size_t i = 0; i < 4; ++i) {
            const size_t source = local_offset + i;
            if (source < data.size()) {
                out |= static_cast<std::uint32_t>(static_cast<unsigned char>(data[source])) << (8 * i);
            }
        }
        return out;
    };
    auto mix = [&]() {
        a -= c; a ^= pa_rot32(c, 4); c += b;
        b -= a; b ^= pa_rot32(a, 6); a += c;
        c -= b; c ^= pa_rot32(b, 8); b += a;
        a -= c; a ^= pa_rot32(c, 16); c += b;
        b -= a; b ^= pa_rot32(a, 19); a += c;
        c -= b; c ^= pa_rot32(b, 4); b += a;
    };
    while (remaining > 12) {
        a += read_tail_u32(offset);
        b += read_tail_u32(offset + 4);
        c += read_tail_u32(offset + 8);
        mix();
        offset += 12;
        remaining -= 12;
    }
    if (remaining == 0) return c;
    a += read_tail_u32(offset);
    b += read_tail_u32(offset + 4);
    c += read_tail_u32(offset + 8);
    c = (c ^ b) - pa_rot32(b, 14);
    a = (a ^ c) - pa_rot32(c, 11);
    b = (b ^ a) - pa_rot32(a, 25);
    c = (c ^ b) - pa_rot32(b, 16);
    a = (a ^ c) - pa_rot32(c, 4);
    b = (b ^ a) - pa_rot32(a, 14);
    c = (c ^ b) - pa_rot32(b, 24);
    return c;
}

static std::vector<std::uint32_t> u32_values_from_bytes(const std::vector<char>& data, size_t offset, size_t count) {
    std::vector<std::uint32_t> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        const size_t at = offset + index * 4u;
        values.push_back(at + 4 <= data.size() ? read_u32(data, at) : 0u);
    }
    return values;
}

static int dds_bytes_per_block(std::uint32_t dxgi_format, const std::string& fourcc) {
    static const std::set<std::uint32_t> block8_formats = {71u, 72u, 80u, 81u};
    static const std::set<std::uint32_t> block16_formats = {74u, 75u, 77u, 78u, 83u, 84u, 94u, 95u, 96u, 98u, 99u};
    if (block8_formats.find(dxgi_format) != block8_formats.end()) return 8;
    if (block16_formats.find(dxgi_format) != block16_formats.end()) return 16;
    const std::string cc = upper_copy(fourcc);
    if (cc == "DXT1" || cc == "BC4U" || cc == "BC4S" || cc == "ATI1") return 8;
    if (cc == "DXT3" || cc == "DXT5" || cc == "BC5U" || cc == "BC5S" || cc == "ATI2" || cc == "RXGB") return 16;
    return 0;
}

static size_t dds_surface_size(
    int width,
    int height,
    std::uint32_t dxgi_format,
    const std::string& fourcc,
    std::uint32_t pf_flags,
    std::uint32_t rgb_bit_count,
    std::uint32_t pitch_or_linear_size,
    int mip_level
) {
    if (width <= 0 || height <= 0) return 0;
    const int bytes_per_block = dds_bytes_per_block(dxgi_format, fourcc);
    if (bytes_per_block > 0) {
        const int block_w = std::max(1, (std::max(1, width) + 3) / 4);
        const int block_h = std::max(1, (std::max(1, height) + 3) / 4);
        return static_cast<size_t>(block_w) * static_cast<size_t>(block_h) * static_cast<size_t>(bytes_per_block);
    }
    constexpr std::uint32_t DDPF_ALPHAPIXELS = 0x1u;
    constexpr std::uint32_t DDPF_ALPHA = 0x2u;
    constexpr std::uint32_t DDPF_RGB = 0x40u;
    constexpr std::uint32_t DDPF_LUMINANCE = 0x20000u;
    if ((pf_flags & (DDPF_LUMINANCE | DDPF_RGB | DDPF_ALPHAPIXELS | DDPF_ALPHA)) != 0 && rgb_bit_count > 0 && rgb_bit_count % 8u == 0) {
        return static_cast<size_t>(width) * static_cast<size_t>(height) * static_cast<size_t>(std::max<std::uint32_t>(1u, rgb_bit_count / 8u));
    }
    if (pitch_or_linear_size > 0) {
        const std::uint32_t row_pitch = std::max<std::uint32_t>(1u, pitch_or_linear_size >> std::max(0, mip_level));
        return static_cast<size_t>(row_pitch) * static_cast<size_t>(std::max(1, height));
    }
    throw std::runtime_error("unsupported DDS partial compression format");
}

struct PathcLookup {
    bool found = false;
    int texture_header_index = -1;
    std::vector<char> compressed_block_infos;
};

struct PathcEntryNative {
    std::uint16_t texture_header_index = 0;
    std::uint8_t collision_start_index = 0;
    std::uint8_t collision_end_index = 0;
    std::vector<char> compressed_block_infos;
};

struct PathcCollisionEntryNative {
    std::uint32_t filename_offset = 0;
    std::uint16_t texture_header_index = 0;
    std::vector<char> compressed_block_infos;
    std::string path;
};

struct PathcCollectionNative {
    std::uint32_t header_size = 0;
    std::vector<std::vector<char>> headers;
    std::unordered_map<std::uint32_t, PathcEntryNative> entries;
    std::unordered_map<std::string, PathcCollisionEntryNative> collisions;

    PathcLookup lookup_file(const std::string& raw_path) const {
        std::string normalized = raw_path;
        std::replace(normalized.begin(), normalized.end(), '\\', '/');
        while (!normalized.empty() && normalized.front() == '/') normalized.erase(normalized.begin());
        const std::uint32_t checksum = calculate_pa_checksum("/" + normalized);
        auto found = entries.find(checksum);
        if (found == entries.end()) return {};
        const PathcEntryNative& entry = found->second;
        if (entry.texture_header_index != 0xFFFFu) {
            const int header_index = static_cast<int>(entry.texture_header_index);
            if (header_index >= 0 && static_cast<size_t>(header_index) < headers.size()) {
                return PathcLookup{true, header_index, entry.compressed_block_infos};
            }
            return {};
        }
        auto collision = collisions.find(normalized);
        if (collision == collisions.end()) return {};
        const int header_index = static_cast<int>(collision->second.texture_header_index);
        if (header_index < 0 || static_cast<size_t>(header_index) >= headers.size()) return {};
        return PathcLookup{true, header_index, collision->second.compressed_block_infos};
    }

    std::vector<char> get_file_header(const std::string& raw_path) const {
        const PathcLookup lookup = lookup_file(raw_path);
        if (!lookup.found || lookup.texture_header_index < 0 || static_cast<size_t>(lookup.texture_header_index) >= headers.size()) {
            throw std::runtime_error("partial DDS PATHC header was not found for " + raw_path);
        }
        const std::vector<char>& header = headers[static_cast<size_t>(lookup.texture_header_index)];
        if (header_size == 0x94u && header.size() >= 0x94u && lookup.compressed_block_infos.size() >= 16u) {
            std::vector<char> patched;
            patched.reserve(header.size());
            patched.insert(patched.end(), header.begin(), header.begin() + 0x20);
            patched.insert(patched.end(), lookup.compressed_block_infos.begin(), lookup.compressed_block_infos.begin() + 16);
            patched.insert(patched.end(), header.begin() + 0x30, header.end());
            return patched;
        }
        return header;
    }
};

static PathcCollectionNative load_pathc_collection_native(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("could not open PATHC file " + path.string());
    std::vector<char> raw((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    if (raw.size() < 32) throw std::runtime_error("PATHC file is too small");
    PathcCollectionNative collection;
    collection.header_size = read_u32(raw, 8);
    const std::uint32_t header_count = read_u32(raw, 12);
    const std::uint32_t entry_count = read_u32(raw, 16);
    const std::uint32_t collision_entry_count = read_u32(raw, 20);
    const std::uint32_t filenames_length = read_u32(raw, 24);
    size_t offset = 28;
    for (std::uint32_t i = 0; i < header_count; ++i) {
        if (offset + collection.header_size > raw.size()) throw std::runtime_error("PATHC texture header table is truncated");
        collection.headers.emplace_back(raw.begin() + static_cast<std::ptrdiff_t>(offset), raw.begin() + static_cast<std::ptrdiff_t>(offset + collection.header_size));
        offset += collection.header_size;
    }
    std::vector<std::uint32_t> checksums;
    checksums.reserve(entry_count);
    for (std::uint32_t i = 0; i < entry_count; ++i) {
        if (offset + 4 > raw.size()) throw std::runtime_error("PATHC checksum table is truncated");
        checksums.push_back(read_u32(raw, offset));
        offset += 4;
    }
    for (std::uint32_t i = 0; i < entry_count; ++i) {
        if (offset + 20 > raw.size()) throw std::runtime_error("PATHC entry table is truncated");
        PathcEntryNative entry;
        entry.texture_header_index = read_u16(raw, offset);
        entry.collision_start_index = static_cast<std::uint8_t>(raw[offset + 2]);
        entry.collision_end_index = static_cast<std::uint8_t>(raw[offset + 3]);
        entry.compressed_block_infos.assign(raw.begin() + static_cast<std::ptrdiff_t>(offset + 4), raw.begin() + static_cast<std::ptrdiff_t>(offset + 20));
        collection.entries[checksums[static_cast<size_t>(i)]] = std::move(entry);
        offset += 20;
    }
    std::vector<PathcCollisionEntryNative> collision_rows;
    collision_rows.reserve(collision_entry_count);
    for (std::uint32_t i = 0; i < collision_entry_count; ++i) {
        if (offset + 24 > raw.size()) throw std::runtime_error("PATHC collision table is truncated");
        PathcCollisionEntryNative collision;
        collision.filename_offset = read_u32(raw, offset);
        collision.texture_header_index = read_u16(raw, offset + 4);
        collision.compressed_block_infos.assign(raw.begin() + static_cast<std::ptrdiff_t>(offset + 8), raw.begin() + static_cast<std::ptrdiff_t>(offset + 24));
        collision_rows.push_back(std::move(collision));
        offset += 24;
    }
    if (offset + filenames_length > raw.size()) throw std::runtime_error("PATHC filename table is truncated");
    for (PathcCollisionEntryNative& collision : collision_rows) {
        if (collision.filename_offset >= filenames_length) continue;
        size_t start = offset + collision.filename_offset;
        size_t end = start;
        while (end < offset + filenames_length && raw[end] != 0) ++end;
        collision.path.assign(raw.begin() + static_cast<std::ptrdiff_t>(start), raw.begin() + static_cast<std::ptrdiff_t>(end));
        std::replace(collision.path.begin(), collision.path.end(), '\\', '/');
        if (!collision.path.empty()) {
            collection.collisions[collision.path] = std::move(collision);
        }
    }
    return collection;
}

static std::map<std::string, PathcCollectionNative>& resident_pathc_cache() {
    static std::map<std::string, PathcCollectionNative> cache;
    return cache;
}

static size_t resident_pathc_cache_count() {
    return resident_pathc_cache().size();
}

static void release_resident_pathc_cache() {
    std::map<std::string, PathcCollectionNative> empty;
    resident_pathc_cache().swap(empty);
}

static const PathcCollectionNative& cached_pathc_collection_native(const fs::path& path) {
    auto& cache = resident_pathc_cache();
    const std::string key = fs::absolute(path).string();
    auto found = cache.find(key);
    if (found != cache.end()) return found->second;
    return cache.emplace(key, load_pathc_collection_native(path)).first->second;
}

static fs::path pathc_path_for_entry(const ArchiveEntryRef& entry) {
    fs::path root = entry.pamt_path.parent_path().parent_path();
    return root / "meta" / "0.pathc";
}

static std::vector<char> reconstruct_partial_dds(const ArchiveEntryRef& entry, const std::vector<char>& data) {
    const fs::path pathc_path = pathc_path_for_entry(entry);
    const PathcCollectionNative& pathc = cached_pathc_collection_native(pathc_path);
    const std::vector<char> header = pathc.get_file_header(entry.path);
    if (header.size() < 0x80u || std::string(header.data(), header.data() + 4) != "DDS ") {
        throw std::runtime_error("Partial DDS PATHC header is missing or invalid");
    }
    const std::uint32_t height = read_u32(header, 12);
    const std::uint32_t width = read_u32(header, 16);
    const std::uint32_t pitch_or_linear_size = read_u32(header, 20);
    const std::uint32_t depth = read_u32(header, 24);
    const std::uint32_t mip_map_count = read_u32(header, 28);
    const std::vector<std::uint32_t> reserved1 = u32_values_from_bytes(header, 32, 11);
    const std::uint32_t pf_flags = read_u32(header, 80);
    const std::string fourcc(header.data() + 84, header.data() + 88);
    const std::uint32_t rgb_bit_count = read_u32(header, 88);
    const std::uint32_t caps2 = read_u32(header, 112);
    const bool is_dx10 = fourcc == "DX10";
    const size_t header_size = is_dx10 ? 0x94u : 0x80u;
    const std::uint32_t dxgi_format = is_dx10 && header.size() >= 0x94u ? read_u32(header, 0x80) : 0u;
    const std::uint32_t dx10_array_size = is_dx10 && header.size() >= 0x94u ? read_u32(header, 0x8C) : 1u;
    const bool multi_chunk_supported_0 = is_dx10 ? dx10_array_size < 2u : true;
    const bool multi_chunk_supported_1 = mip_map_count > 5u && caps2 == 0u && depth < 2u;
    const bool use_single_chunk = !multi_chunk_supported_0 || !multi_chunk_supported_1;

    std::vector<std::uint32_t> compressed_block_sizes;
    std::vector<size_t> decompressed_block_sizes;
    if (use_single_chunk) {
        compressed_block_sizes.push_back(reserved1.size() > 0 ? reserved1[0] : 0u);
        decompressed_block_sizes.push_back(reserved1.size() > 1 ? static_cast<size_t>(reserved1[1]) : 0u);
    } else {
        for (size_t i = 0; i < 4 && i < reserved1.size(); ++i) {
            compressed_block_sizes.push_back(reserved1[i]);
        }
        int current_width = static_cast<int>(std::max<std::uint32_t>(1u, width));
        int current_height = static_cast<int>(std::max<std::uint32_t>(1u, height));
        const int levels = static_cast<int>(std::min<std::uint32_t>(4u, std::max<std::uint32_t>(1u, mip_map_count)));
        for (int level = 0; level < levels; ++level) {
            decompressed_block_sizes.push_back(dds_surface_size(
                current_width,
                current_height,
                dxgi_format,
                fourcc,
                pf_flags,
                rgb_bit_count,
                pitch_or_linear_size,
                level));
            current_width = std::max(1, current_width >> 1);
            current_height = std::max(1, current_height >> 1);
        }
    }
    if (data.size() >= header_size && data.size() >= 0x80u && std::string(data.data(), data.data() + 4) == "DDS ") {
        const std::vector<std::uint32_t> payload_reserved = u32_values_from_bytes(data, 32, 11);
        std::vector<std::uint32_t> payload_compressed_sizes;
        std::vector<size_t> payload_decompressed_sizes;
        if (use_single_chunk) {
            payload_compressed_sizes.push_back(payload_reserved.size() > 0 ? payload_reserved[0] : 0u);
            payload_decompressed_sizes.push_back(payload_reserved.size() > 1 ? static_cast<size_t>(payload_reserved[1]) : 0u);
        } else {
            for (size_t i = 0; i < compressed_block_sizes.size() && i < payload_reserved.size(); ++i) {
                payload_compressed_sizes.push_back(payload_reserved[i]);
            }
            payload_decompressed_sizes = decompressed_block_sizes;
        }
        std::uint64_t payload_bytes_needed = 0;
        for (std::uint32_t value : payload_compressed_sizes) {
            if (value > 0) payload_bytes_needed += value;
        }
        std::uint64_t payload_decompressed_needed = 0;
        for (size_t value : payload_decompressed_sizes) {
            if (value > 0) payload_decompressed_needed += static_cast<std::uint64_t>(value);
        }
        std::uint64_t current_bytes_needed = 0;
        for (std::uint32_t value : compressed_block_sizes) {
            if (value > 0) current_bytes_needed += value;
        }
        const bool payload_chunk_table_is_plausible =
            payload_bytes_needed > 0
            && header_size + payload_bytes_needed <= data.size()
            && payload_decompressed_needed > 0
            && payload_bytes_needed <= payload_decompressed_needed
            && (
                current_bytes_needed == 0
                || header_size + current_bytes_needed > data.size()
                || payload_bytes_needed < current_bytes_needed
            );
        if (payload_chunk_table_is_plausible) {
            compressed_block_sizes = std::move(payload_compressed_sizes);
            if (use_single_chunk) {
                decompressed_block_sizes = std::move(payload_decompressed_sizes);
            }
        }
    }

    size_t current_data_offset = header_size;
    std::vector<char> output;
    output.reserve(static_cast<size_t>(entry.orig_size));
    output.insert(output.end(), header.begin(), header.begin() + static_cast<std::ptrdiff_t>(std::min(header_size, header.size())));
    const size_t count = std::min(compressed_block_sizes.size(), decompressed_block_sizes.size());
    for (size_t i = 0; i < count; ++i) {
        const std::uint32_t compressed_size = compressed_block_sizes[i];
        const size_t decompressed_size = decompressed_block_sizes[i];
        if (compressed_size == 0 || decompressed_size == 0) continue;
        if (current_data_offset + compressed_size > data.size()) {
            throw std::runtime_error("Partial DDS block is truncated");
        }
        std::vector<char> block(data.begin() + static_cast<std::ptrdiff_t>(current_data_offset), data.begin() + static_cast<std::ptrdiff_t>(current_data_offset + compressed_size));
        if (compressed_size != decompressed_size) {
            block = lz4_decompress_block(block, decompressed_size);
            if (block.size() != decompressed_size) {
                throw std::runtime_error("Partial DDS LZ4 block decompressed to the wrong size");
            }
        }
        output.insert(output.end(), block.begin(), block.end());
        current_data_offset += compressed_size;
    }
    if (current_data_offset < data.size()) {
        output.insert(output.end(), data.begin() + static_cast<std::ptrdiff_t>(current_data_offset), data.end());
    }
    return output;
}

static std::vector<char> maybe_decompress_partial_par(const ArchiveEntryRef& entry, const std::vector<char>& data) {
    if (entry.compression_type() != 1 || data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") {
        return {};
    }
    struct Slot {
        std::uint32_t comp_size = 0;
        std::uint32_t decomp_size = 0;
        size_t offset = 0;
    };
    std::vector<Slot> slots;
    size_t file_offset = 0x50;
    size_t rebuilt_size = 0x50;
    bool saw_compressed = false;
    for (int slot = 0; slot < 8; ++slot) {
        const size_t slot_offset = 0x10u + static_cast<size_t>(slot) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_offset);
        const std::uint32_t decomp_size = read_u32(data, slot_offset + 4);
        if (decomp_size == 0) continue;
        const std::uint32_t chunk_size = comp_size > 0 ? comp_size : decomp_size;
        if (chunk_size == 0 || file_offset + chunk_size > data.size()) return {};
        if (decomp_size > entry.orig_size || rebuilt_size + decomp_size > entry.orig_size) return {};
        slots.push_back(Slot{comp_size, decomp_size, file_offset});
        file_offset += chunk_size;
        rebuilt_size += decomp_size;
        if (comp_size > 0) saw_compressed = true;
    }
    if (!saw_compressed || file_offset != data.size() || rebuilt_size != entry.orig_size) return {};
    std::vector<char> rebuilt(data.begin(), data.begin() + 0x50);
    for (const Slot& slot : slots) {
        const size_t chunk_size = slot.comp_size > 0 ? slot.comp_size : slot.decomp_size;
        std::vector<char> chunk(data.begin() + static_cast<std::ptrdiff_t>(slot.offset), data.begin() + static_cast<std::ptrdiff_t>(slot.offset + chunk_size));
        if (slot.comp_size > 0) {
            chunk = lz4_decompress_block(chunk, slot.decomp_size);
            if (chunk.size() != slot.decomp_size) return {};
        }
        rebuilt.insert(rebuilt.end(), chunk.begin(), chunk.end());
    }
    if (rebuilt.size() != entry.orig_size) return {};
    for (int slot = 0; slot < 8; ++slot) {
        const size_t off = 0x10u + static_cast<size_t>(slot) * 8u;
        if (off + 4 <= rebuilt.size()) {
            rebuilt[off + 0] = 0;
            rebuilt[off + 1] = 0;
            rebuilt[off + 2] = 0;
            rebuilt[off + 3] = 0;
        }
    }
    return rebuilt;
}

static std::vector<char> decode_archive_ref_bytes(const ArchiveEntryRef& entry, const std::vector<char>& raw) {
    std::vector<char> data = raw;
    if (entry.encrypted()) {
        if (entry.encryption_type() != 3) {
            throw std::runtime_error("unsupported archive encryption type " + std::to_string(entry.encryption_type()));
        }
        data = crypt_chacha20_filename(data, entry.basename.empty() ? basename_from_path(entry.path) : entry.basename);
    }
    if (!entry.compressed()) return data;
    if (entry.compression_type() == 2) {
        return lz4_decompress_block(data, static_cast<size_t>(entry.orig_size));
    }
    if (entry.compression_type() == 1) {
        std::vector<char> partial_par = maybe_decompress_partial_par(entry, data);
        if (!partial_par.empty()) return partial_par;
        if (entry.extension == ".dds") {
            return reconstruct_partial_dds(entry, data);
        }
        return data;
    }
    if (entry.extension == ".dds" && data.size() >= 4 && std::string(data.data(), data.data() + 4) == "DDS " && data.size() >= 128) {
        std::vector<char> padded = data;
        padded.resize(static_cast<size_t>(entry.orig_size), 0);
        return padded;
    }
    throw std::runtime_error("unsupported archive compression type " + std::to_string(entry.compression_type()));
}

static std::string archive_ref_identity(const ArchiveEntryRef& entry) {
    return entry.pamt_path.string() + "|" + entry.paz_file.string() + "|" + entry.path + "|" +
        std::to_string(entry.offset) + "|" + std::to_string(entry.comp_size) + "|" +
        std::to_string(entry.orig_size) + "|" + std::to_string(entry.flags) + "|" +
        std::to_string(entry.paz_index);
}

struct DecodedEntryCacheValue {
    std::vector<char> bytes;
    size_t last_used = 0;
};

static std::unordered_map<std::string, DecodedEntryCacheValue> g_decoded_entry_cache;
static size_t g_decoded_entry_cache_bytes = 0;
static size_t g_decoded_entry_cache_clock = 0;
static std::uint64_t g_decoded_entry_cache_hits = 0;
static std::uint64_t g_decoded_entry_cache_misses = 0;
static std::uint64_t g_decoded_entry_cache_evictions = 0;
static std::uint64_t g_service_job_count = 0;
static constexpr size_t kDecodedEntryCacheMaxEntries = 512;
static constexpr size_t kDecodedEntryCacheMaxBytes = 256ull * 1024ull * 1024ull;
static constexpr size_t kDecodedEntryCacheMaxSingleBytes = 64ull * 1024ull * 1024ull;
static constexpr size_t kDecodedEntryCacheRecycleBytes = 192ull * 1024ull * 1024ull;
static constexpr std::uint64_t kServiceMaxJobs = 32;
static constexpr unsigned long long kServicePrivateRecycleBytes = 512ull * 1024ull * 1024ull;

static size_t decoded_entry_cache_entries() {
    return g_decoded_entry_cache.size();
}

static size_t decoded_entry_cache_bytes() {
    return g_decoded_entry_cache_bytes;
}

static std::uint64_t decoded_entry_cache_hits() {
    return g_decoded_entry_cache_hits;
}

static std::uint64_t decoded_entry_cache_misses() {
    return g_decoded_entry_cache_misses;
}

static std::uint64_t decoded_entry_cache_evictions() {
    return g_decoded_entry_cache_evictions;
}

static std::string service_recycle_reason(const cdmw_native_diag::ProcessMemorySnapshot& memory) {
    if (g_service_job_count >= kServiceMaxJobs) {
        return "job_count";
    }
    if (decoded_entry_cache_bytes() > kDecodedEntryCacheRecycleBytes) {
        return "decoded_cache_bytes";
    }
    if (memory.ok && memory.private_bytes > kServicePrivateRecycleBytes) {
        return "process_private_bytes";
    }
    return "";
}

static void prune_decoded_entry_cache() {
    while (
        g_decoded_entry_cache.size() > kDecodedEntryCacheMaxEntries ||
        g_decoded_entry_cache_bytes > kDecodedEntryCacheMaxBytes
    ) {
        auto oldest = g_decoded_entry_cache.end();
        size_t oldest_tick = std::numeric_limits<size_t>::max();
        for (auto it = g_decoded_entry_cache.begin(); it != g_decoded_entry_cache.end(); ++it) {
            if (it->second.last_used < oldest_tick) {
                oldest_tick = it->second.last_used;
                oldest = it;
            }
        }
        if (oldest == g_decoded_entry_cache.end()) break;
        g_decoded_entry_cache_bytes -= oldest->second.bytes.size();
        g_decoded_entry_cache.erase(oldest);
        ++g_decoded_entry_cache_evictions;
    }
}

static std::vector<char> read_archive_ref_decoded_bytes(const ArchiveEntryRef& entry) {
    const std::string key = archive_ref_identity(entry);
    auto found = g_decoded_entry_cache.find(key);
    if (found != g_decoded_entry_cache.end()) {
        ++g_decoded_entry_cache_hits;
        found->second.last_used = ++g_decoded_entry_cache_clock;
        return found->second.bytes;
    }
    ++g_decoded_entry_cache_misses;
    std::vector<char> decoded = decode_archive_ref_bytes(entry, read_archive_ref_raw_bytes(entry));
    if (decoded.size() <= kDecodedEntryCacheMaxSingleBytes) {
        g_decoded_entry_cache_bytes += decoded.size();
        g_decoded_entry_cache.emplace(key, DecodedEntryCacheValue{decoded, ++g_decoded_entry_cache_clock});
        prune_decoded_entry_cache();
    }
    return decoded;
}

static std::vector<char> read_entry_decoded_bytes(const EntryJob& job) {
    if (!job.entry.path.empty()) return read_archive_ref_decoded_bytes(job.entry);
    std::vector<char> raw = read_entry_raw_bytes(job);
    ArchiveEntryRef ref;
    ref.path = job.path;
    ref.extension = job.extension;
    ref.paz_file = job.paz_file;
    ref.offset = job.offset;
    ref.comp_size = job.comp_size;
    ref.orig_size = job.orig_size;
    ref.flags = job.flags;
    return decode_archive_ref_bytes(ref, raw);
}
