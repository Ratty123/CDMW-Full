
static void write_binary(const fs::path& path, const std::vector<char>& data) {
    if (!path.parent_path().empty()) {
        fs::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("could not write " + path.string());
    }
    if (!data.empty()) {
        out.write(data.data(), static_cast<std::streamsize>(data.size()));
    }
}

static std::string safe_filename(std::string value) {
    if (value.empty()) value = "texture";
    for (char& ch : value) {
        const unsigned char u = static_cast<unsigned char>(ch);
        if (!(std::isalnum(u) || ch == '.' || ch == '_' || ch == '-')) {
            ch = '_';
        }
    }
    return value;
}

static std::uint64_t fnv1a64(const std::string& text) {
    std::uint64_t hash = 1469598103934665603ull;
    for (unsigned char ch : text) {
        hash ^= static_cast<std::uint64_t>(ch);
        hash *= 1099511628211ull;
    }
    return hash;
}

static std::string hex64(std::uint64_t value) {
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << value;
    return out.str();
}

static std::uint32_t rot32(std::uint32_t value, int shift) {
    return (value << shift) | (value >> (32 - shift));
}

static std::uint32_t lookup3_finalize_c(std::uint32_t a, std::uint32_t b, std::uint32_t c) {
    c = (c ^ b) - rot32(b, 14);
    a = (a ^ c) - rot32(c, 11);
    b = (b ^ a) - rot32(a, 25);
    c = (c ^ b) - rot32(b, 16);
    a = (a ^ c) - rot32(c, 4);
    b = (b ^ a) - rot32(a, 14);
    c = (c ^ b) - rot32(b, 24);
    return c;
}

static std::uint32_t read_u32_padded(const std::vector<unsigned char>& data, size_t offset) {
    std::uint32_t value = 0;
    for (size_t i = 0; i < 4; ++i) {
        if (offset + i < data.size()) {
            value |= static_cast<std::uint32_t>(data[offset + i]) << (i * 8);
        }
    }
    return value;
}

static std::uint32_t hashlittle_bytes(const std::vector<unsigned char>& data, std::uint32_t initval) {
    size_t length = data.size();
    size_t remaining = length;
    std::uint32_t a = 0xDEADBEEFu + static_cast<std::uint32_t>(length) + initval;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    while (remaining > 12) {
        a += read_u32_padded(data, offset);
        b += read_u32_padded(data, offset + 4);
        c += read_u32_padded(data, offset + 8);
        a -= c; a ^= rot32(c, 4); c += b;
        b -= a; b ^= rot32(a, 6); a += c;
        c -= b; c ^= rot32(b, 8); b += a;
        a -= c; a ^= rot32(c, 16); c += b;
        b -= a; b ^= rot32(a, 19); a += c;
        c -= b; c ^= rot32(b, 4); b += a;
        offset += 12;
        remaining -= 12;
    }
    if (remaining >= 12) {
        c += read_u32_padded(data, offset + 8);
    } else if (remaining >= 9) {
        c += read_u32_padded(data, offset + 8) & (0xFFFFFFFFu >> (8u * (12u - static_cast<unsigned int>(remaining))));
    }
    if (remaining >= 8) {
        b += read_u32_padded(data, offset + 4);
    } else if (remaining >= 5) {
        b += read_u32_padded(data, offset + 4) & (0xFFFFFFFFu >> (8u * (8u - static_cast<unsigned int>(remaining))));
    }
    if (remaining >= 4) {
        a += read_u32_padded(data, offset);
    } else if (remaining >= 1) {
        a += read_u32_padded(data, offset) & (0xFFFFFFFFu >> (8u * (4u - static_cast<unsigned int>(remaining))));
    } else {
        return c;
    }
    return lookup3_finalize_c(a, b, c);
}

static void chacha_quarter_round(std::uint32_t& a, std::uint32_t& b, std::uint32_t& c, std::uint32_t& d) {
    a += b; d ^= a; d = rot32(d, 16);
    c += d; b ^= c; b = rot32(b, 12);
    a += b; d ^= a; d = rot32(d, 8);
    c += d; b ^= c; b = rot32(b, 7);
}

static void chacha20_block(const std::array<std::uint32_t, 16>& state, std::array<unsigned char, 64>& out) {
    std::array<std::uint32_t, 16> working = state;
    for (int i = 0; i < 10; ++i) {
        chacha_quarter_round(working[0], working[4], working[8], working[12]);
        chacha_quarter_round(working[1], working[5], working[9], working[13]);
        chacha_quarter_round(working[2], working[6], working[10], working[14]);
        chacha_quarter_round(working[3], working[7], working[11], working[15]);
        chacha_quarter_round(working[0], working[5], working[10], working[15]);
        chacha_quarter_round(working[1], working[6], working[11], working[12]);
        chacha_quarter_round(working[2], working[7], working[8], working[13]);
        chacha_quarter_round(working[3], working[4], working[9], working[14]);
    }
    for (size_t i = 0; i < 16; ++i) {
        working[i] += state[i];
        out[i * 4 + 0] = static_cast<unsigned char>((working[i] >> 0) & 0xFF);
        out[i * 4 + 1] = static_cast<unsigned char>((working[i] >> 8) & 0xFF);
        out[i * 4 + 2] = static_cast<unsigned char>((working[i] >> 16) & 0xFF);
        out[i * 4 + 3] = static_cast<unsigned char>((working[i] >> 24) & 0xFF);
    }
}

static std::vector<char> crypt_chacha20_filename(const std::vector<char>& data, const std::string& filename) {
    std::string base = lower_copy(basename_from_path(filename));
    std::vector<unsigned char> base_bytes(base.begin(), base.end());
    const std::uint32_t seed = hashlittle_bytes(base_bytes, 0x000C5EDEu);
    const std::uint32_t key_base = seed ^ 0x60616263u;
    const std::array<std::uint32_t, 8> deltas = {
        0x00000000u, 0x0A0A0A0Au, 0x0C0C0C0Cu, 0x06060606u,
        0x0E0E0E0Eu, 0x0A0A0A0Au, 0x06060606u, 0x02020202u,
    };
    std::array<std::uint32_t, 16> state = {
        0x61707865u, 0x3320646Eu, 0x79622D32u, 0x6B206574u,
        key_base ^ deltas[0], key_base ^ deltas[1], key_base ^ deltas[2], key_base ^ deltas[3],
        key_base ^ deltas[4], key_base ^ deltas[5], key_base ^ deltas[6], key_base ^ deltas[7],
        seed, seed, seed, seed,
    };
    std::vector<char> out(data.size());
    size_t offset = 0;
    while (offset < data.size()) {
        std::array<unsigned char, 64> block{};
        chacha20_block(state, block);
        const size_t n = std::min<size_t>(64, data.size() - offset);
        for (size_t i = 0; i < n; ++i) {
            out[offset + i] = static_cast<char>(static_cast<unsigned char>(data[offset + i]) ^ block[i]);
        }
        ++state[12];
        if (state[12] == 0) ++state[13];
        offset += n;
    }
    return out;
}

class VfsPathResolver {
public:
    explicit VfsPathResolver(const std::vector<char>& name_block) : name_block_(name_block) {
        cache_[0xFFFFFFFFu] = "";
    }

    std::string get_full_path(std::uint32_t offset) {
        if (offset == 0xFFFFFFFFu || offset >= name_block_.size()) return "";
        auto cached = cache_.find(offset);
        if (cached != cache_.end()) return cached->second;
        std::vector<std::pair<std::uint32_t, std::string>> parts;
        std::uint32_t current = offset;
        std::string base;
        std::set<std::uint32_t> seen;
        while (current != 0xFFFFFFFFu) {
            if (!seen.insert(current).second) break;
            auto hit = cache_.find(current);
            if (hit != cache_.end()) {
                base = hit->second;
                break;
            }
            if (static_cast<size_t>(current) + 5 > name_block_.size()) break;
            const std::uint32_t parent = read_u32(name_block_, current);
            const std::uint8_t part_len = static_cast<std::uint8_t>(name_block_[current + 4]);
            if (static_cast<size_t>(current) + 5 + part_len > name_block_.size()) break;
            std::string part(name_block_.data() + current + 5, name_block_.data() + current + 5 + part_len);
            parts.emplace_back(current, part);
            current = parent;
            if (parts.size() > 255) break;
        }
        std::string built = base;
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
            built += it->second;
            if (cache_.size() < 200000) {
                cache_[it->first] = built;
            }
        }
        return built;
    }

private:
    const std::vector<char>& name_block_;
    std::unordered_map<std::uint32_t, std::string> cache_;
};

struct PamtIndex {
    fs::path pamt_path;
    std::unordered_map<std::string, std::vector<ArchiveEntryRef>> by_basename;
    std::vector<ArchiveEntryRef> material_sidecars;
    size_t entry_count = 0;
};

static std::vector<char> read_pamt_bytes(const fs::path& pamt_path) {
    std::ifstream in(pamt_path, std::ios::binary);
    if (!in) throw std::runtime_error("could not open PAMT file " + pamt_path.string());
    in.seekg(0, std::ios::end);
    const auto size_pos = in.tellg();
    if (size_pos < 0) throw std::runtime_error("could not determine PAMT size");
    in.seekg(0, std::ios::beg);
    std::vector<char> data(static_cast<size_t>(size_pos));
    if (!data.empty()) {
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) {
            throw std::runtime_error("short read from PAMT file");
        }
    }
    return data;
}

static PamtIndex parse_pamt_index(const fs::path& pamt_path) {
    if (pamt_path.empty()) {
        throw std::runtime_error("job has no pamt_path");
    }
    const std::vector<char> data = read_pamt_bytes(pamt_path);
    if (data.size() < 12) throw std::runtime_error("PAMT file is too small");
    size_t off = 0;
    (void)read_u32(data, off);
    off += 4;
    const std::uint32_t paz_count = read_u32(data, off);
    off += 8;
    off += static_cast<size_t>(paz_count) * 12u;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT directory block length is truncated");
    const std::uint32_t dir_block_size = read_u32(data, off);
    off += 4;
    if (off + dir_block_size > data.size()) throw std::runtime_error("PAMT directory block is truncated");
    std::vector<char> directory_data(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + dir_block_size));
    off += dir_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT filename block length is truncated");
    const std::uint32_t file_name_block_size = read_u32(data, off);
    off += 4;
    if (off + file_name_block_size > data.size()) throw std::runtime_error("PAMT filename block is truncated");
    std::vector<char> file_names(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + file_name_block_size));
    off += file_name_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT folder count is truncated");
    const std::uint32_t folder_count = read_u32(data, off);
    off += 4;
    const size_t folder_table_offset = off;
    const size_t folder_table_size = static_cast<size_t>(folder_count) * 16u;
    if (off + folder_table_size > data.size()) throw std::runtime_error("PAMT folder table is truncated");
    off += folder_table_size;
    if (off + 4 > data.size()) throw std::runtime_error("PAMT file count is truncated");
    const std::uint32_t file_count = read_u32(data, off);
    off += 4;
    const size_t file_table_offset = off;
    const size_t file_record_size = 20u;
    if (off + static_cast<size_t>(file_count) * file_record_size > data.size()) {
        throw std::runtime_error("PAMT file table is truncated");
    }

    VfsPathResolver file_resolver(file_names);
    VfsPathResolver dir_resolver(directory_data);
    struct FolderRange {
        std::uint32_t start = 0;
        std::uint32_t end = 0;
        std::string path;
    };
    std::vector<FolderRange> folder_ranges;
    folder_ranges.reserve(folder_count);
    for (std::uint32_t i = 0; i < folder_count; ++i) {
        const size_t base = folder_table_offset + static_cast<size_t>(i) * 16u;
        const std::uint32_t name_offset = read_u32(data, base + 4);
        const std::uint32_t start = read_u32(data, base + 8);
        const std::uint32_t count = read_u32(data, base + 12);
        if (count == 0) continue;
        std::string folder = dir_resolver.get_full_path(name_offset);
        std::replace(folder.begin(), folder.end(), '\\', '/');
        while (!folder.empty() && folder.front() == '/') folder.erase(folder.begin());
        while (!folder.empty() && folder.back() == '/') folder.pop_back();
        folder_ranges.push_back(FolderRange{start, start + count, folder});
    }
    std::sort(folder_ranges.begin(), folder_ranges.end(), [](const FolderRange& a, const FolderRange& b) {
        return a.start < b.start;
    });

    PamtIndex index;
    index.pamt_path = pamt_path;
    index.entry_count = file_count;
    size_t folder_cursor = 0;
    for (std::uint32_t entry_index = 0; entry_index < file_count; ++entry_index) {
        const size_t base = file_table_offset + static_cast<size_t>(entry_index) * file_record_size;
        const std::uint32_t name_offset = read_u32(data, base);
        const std::uint32_t paz_offset = read_u32(data, base + 4);
        const std::uint32_t comp_size = read_u32(data, base + 8);
        const std::uint32_t orig_size = read_u32(data, base + 12);
        const std::uint16_t paz_index = read_u16(data, base + 16);
        const std::uint16_t flags = read_u16(data, base + 18);
        std::string relative = file_resolver.get_full_path(name_offset);
        std::replace(relative.begin(), relative.end(), '\\', '/');
        while (!relative.empty() && relative.front() == '/') relative.erase(relative.begin());
        while (folder_cursor < folder_ranges.size() && entry_index >= folder_ranges[folder_cursor].end) {
            ++folder_cursor;
        }
        std::string folder;
        if (folder_cursor < folder_ranges.size()) {
            const FolderRange& range = folder_ranges[folder_cursor];
            if (entry_index >= range.start && entry_index < range.end) {
                folder = range.path;
            }
        }
        const std::string full_path = folder.empty() ? relative : (folder + "/" + relative);
        ArchiveEntryRef ref;
        ref.path = full_path;
        ref.basename = basename_from_path(full_path);
        ref.extension = extension_from_path(full_path);
        ref.pamt_path = pamt_path;
        ref.paz_index = paz_index;
        ref.paz_file = pamt_path.parent_path() / (std::to_string(paz_index) + ".paz");
        ref.offset = paz_offset;
        ref.comp_size = comp_size;
        ref.orig_size = orig_size;
        ref.flags = flags;
        const std::string ref_path_lower = lower_copy(ref.path);
        const bool pbd_xml_sidecar =
            ref.extension == ".xml" &&
            (
                ref_path_lower.find("/descriptors/pbd/") != std::string::npos ||
                lower_copy(ref.basename) == "pbdconfig.xml"
            );
        const bool material_sidecar =
            ref.extension == ".pami" ||
            ref.extension == ".pac_xml" ||
            ref.extension == ".pam_xml" ||
            ref.extension == ".pamlod_xml" ||
            ref.extension == ".material" ||
            ref.extension == ".technique" ||
            ref.extension == ".prefab" ||
            ref.extension == ".prefabdata_xml" ||
            ref.extension == ".meshinfo" ||
            pbd_xml_sidecar;
        const bool lookup_relevant =
            ref.extension == ".dds" ||
            ref.extension == ".pac" ||
            ref.extension == ".pam" ||
            ref.extension == ".pamlod" ||
            ref.extension == ".hkx" ||
            ref.extension == ".pab" ||
            material_sidecar;
        if (lookup_relevant) {
            index.by_basename[lower_copy(ref.basename)].push_back(ref);
        }
        if (material_sidecar) {
            index.material_sidecars.push_back(ref);
        }
    }
    return index;
}

static const PamtIndex& cached_pamt_index(const fs::path& pamt_path) {
    static std::map<std::string, PamtIndex> cache;
    const std::string key = fs::absolute(pamt_path).string();
    auto it = cache.find(key);
    if (it == cache.end()) {
        it = cache.emplace(key, parse_pamt_index(pamt_path)).first;
    }
    return it->second;
}

std::string fourcc_from_bytes(const std::vector<char>& data) {
    if (data.size() < 4) return "";
    std::string value(data.data(), data.data() + 4);
    for (char& ch : value) {
        if (static_cast<unsigned char>(ch) < 0x20 || static_cast<unsigned char>(ch) > 0x7e) ch = '.';
    }
    return value;
}

static float vec_dot(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

static Vec3 vec_cross(const Vec3& a, const Vec3& b) {
    return Vec3{
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

static Vec3 vec_add(const Vec3& a, const Vec3& b) {
    return Vec3{a.x + b.x, a.y + b.y, a.z + b.z};
}

static Vec3 vec_sub(const Vec3& a, const Vec3& b) {
    return Vec3{a.x - b.x, a.y - b.y, a.z - b.z};
}

static Vec3 vec_mul(const Vec3& value, float scale) {
    return Vec3{value.x * scale, value.y * scale, value.z * scale};
}

static Vec3 vec_normalize(const Vec3& value, const Vec3& fallback = Vec3{0.0f, 1.0f, 0.0f}) {
    const float len2 = vec_dot(value, value);
    if (len2 <= 1.0e-12f || !std::isfinite(len2)) return fallback;
    const float inv = 1.0f / std::sqrt(len2);
    return Vec3{value.x * inv, value.y * inv, value.z * inv};
}

static std::vector<ParSection> parse_par_sections(const std::vector<char>& data) {
    std::vector<ParSection> sections;
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") return sections;
    std::uint32_t offset = 0x50;
    for (int i = 0; i < 8; ++i) {
        const size_t slot_off = 0x10u + static_cast<size_t>(i) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_off);
        const std::uint32_t decomp_size = read_u32(data, slot_off + 4);
        const std::uint32_t stored_size = comp_size > 0 ? comp_size : decomp_size;
        if (decomp_size == 0) continue;
        if (offset + stored_size > data.size()) return {};
        if (comp_size > 0 && comp_size < decomp_size) {
            // Callers that need compressed internal PAR sections should
            // normalize the container before using this table parser.
            return {};
        }
        sections.push_back(ParSection{i, offset, decomp_size});
        offset += stored_size;
    }
    return sections;
}

static std::vector<char> decompress_internal_par_sections(const std::vector<char>& data) {
    if (data.size() < 0x50 || std::string(data.data(), data.data() + 4) != "PAR ") return {};
    struct Slot {
        int index = 0;
        std::uint32_t comp_size = 0;
        std::uint32_t decomp_size = 0;
        size_t offset = 0;
    };
    std::vector<Slot> slots;
    size_t file_offset = 0x50u;
    size_t rebuilt_size = 0x50u;
    bool saw_compressed = false;
    for (int i = 0; i < 8; ++i) {
        const size_t slot_off = 0x10u + static_cast<size_t>(i) * 8u;
        const std::uint32_t comp_size = read_u32(data, slot_off);
        const std::uint32_t decomp_size = read_u32(data, slot_off + 4);
        if (decomp_size == 0) continue;
        const std::uint32_t stored_size = comp_size > 0 ? comp_size : decomp_size;
        if (stored_size == 0 || file_offset + stored_size > data.size()) return {};
        if (comp_size > 0) saw_compressed = true;
        slots.push_back(Slot{i, comp_size, decomp_size, file_offset});
        file_offset += stored_size;
        rebuilt_size += decomp_size;
    }
    if (!saw_compressed || slots.empty() || file_offset != data.size()) return {};
    std::vector<char> rebuilt;
    rebuilt.reserve(rebuilt_size);
    rebuilt.insert(rebuilt.end(), data.begin(), data.begin() + 0x50);
    for (const Slot& slot : slots) {
        const size_t stored_size = slot.comp_size > 0 ? slot.comp_size : slot.decomp_size;
        std::vector<char> chunk(
            data.begin() + static_cast<std::ptrdiff_t>(slot.offset),
            data.begin() + static_cast<std::ptrdiff_t>(slot.offset + stored_size)
        );
        if (slot.comp_size > 0) {
            chunk = lz4_decompress_block(chunk, slot.decomp_size);
            if (chunk.size() != slot.decomp_size) return {};
        } else if (chunk.size() != slot.decomp_size) {
            return {};
        }
        rebuilt.insert(rebuilt.end(), chunk.begin(), chunk.end());
    }
    if (rebuilt.size() != rebuilt_size) return {};
    for (int i = 0; i < 8; ++i) {
        const size_t slot_off = 0x10u + static_cast<size_t>(i) * 8u;
        if (slot_off + 8u > rebuilt.size()) return {};
        const std::uint32_t decomp_size = read_u32(rebuilt, slot_off + 4);
        rebuilt[slot_off + 0] = 0;
        rebuilt[slot_off + 1] = 0;
        rebuilt[slot_off + 2] = 0;
        rebuilt[slot_off + 3] = 0;
        rebuilt[slot_off + 4] = static_cast<char>(decomp_size & 0xFFu);
        rebuilt[slot_off + 5] = static_cast<char>((decomp_size >> 8) & 0xFFu);
        rebuilt[slot_off + 6] = static_cast<char>((decomp_size >> 16) & 0xFFu);
        rebuilt[slot_off + 7] = static_cast<char>((decomp_size >> 24) & 0xFFu);
    }
    return rebuilt;
}

static int find_bytes(const std::vector<char>& data, const std::vector<unsigned char>& pattern, size_t start, size_t end) {
    if (pattern.empty() || start >= end || pattern.size() > end - start) return -1;
    for (size_t i = start; i + pattern.size() <= end; ++i) {
        bool ok = true;
        for (size_t j = 0; j < pattern.size(); ++j) {
            if (static_cast<unsigned char>(data[i + j]) != pattern[j]) {
                ok = false;
                break;
            }
        }
        if (ok) return static_cast<int>(i);
    }
    return -1;
}

static std::pair<std::string, std::string> find_descriptor_names(
    const std::vector<char>& data,
    size_t region_start,
    size_t desc_start
) {
    std::vector<std::string> names;
    size_t cursor = desc_start;
    for (int n = 0; n < 2; ++n) {
        bool found = false;
        for (size_t back = 1; back < 200 && cursor >= region_start + back; ++back) {
            const size_t pos = cursor - back;
            const unsigned char candidate_len = static_cast<unsigned char>(data[pos]);
            if (candidate_len == 0 || candidate_len != back - 1) continue;
            bool ascii = true;
            for (size_t p = pos + 1; p < cursor; ++p) {
                const unsigned char ch = static_cast<unsigned char>(data[p]);
                if (ch < 32 || ch >= 127) {
                    ascii = false;
                    break;
                }
            }
            if (!ascii || cursor <= pos + 1) continue;
            names.emplace_back(data.data() + pos + 1, data.data() + cursor);
            cursor = pos;
            found = true;
            break;
        }
        if (!found) {
            std::ostringstream unknown;
            unknown << "unknown_" << std::hex << (desc_start - region_start);
            names.push_back(unknown.str());
        }
    }
    std::reverse(names.begin(), names.end());
    return {names.size() > 0 ? names[0] : "", names.size() > 1 ? names[1] : ""};
}

static std::vector<PacDescriptor> find_pac_descriptors(
    const std::vector<char>& data,
    const ParSection& sec0,
    int n_lods
) {
    std::vector<PacDescriptor> descriptors;
    std::set<size_t> seen_starts;
    const size_t region_start = sec0.offset;
    const size_t region_end = static_cast<size_t>(sec0.offset) + sec0.size;
    if (region_end > data.size() || region_start >= region_end) return descriptors;
    const int pad_len = std::max(4, n_lods);

    auto append_descriptor = [&](size_t pattern_pos, int stored_lod_count, int vc_off, int ic_off) {
        if (pattern_pos < 35) return;
        const size_t desc_start = pattern_pos - 35;
        if (desc_start < region_start || !seen_starts.insert(desc_start).second) return;
        if (desc_start + static_cast<size_t>(ic_off) + static_cast<size_t>(stored_lod_count) * 4u > region_end) return;
        if (static_cast<unsigned char>(data[desc_start]) != 0x01) return;
        PacDescriptor desc;
        try {
            desc.bbox_min = Vec3{
                read_f32(data, desc_start + 3 + 2 * 4),
                read_f32(data, desc_start + 3 + 3 * 4),
                read_f32(data, desc_start + 3 + 4 * 4),
            };
            desc.bbox_extent = Vec3{
                read_f32(data, desc_start + 3 + 5 * 4),
                read_f32(data, desc_start + 3 + 6 * 4),
                read_f32(data, desc_start + 3 + 7 * 4),
            };
            for (int i = 0; i < stored_lod_count && i < pad_len && i < 10; ++i) {
                desc.vertex_counts[static_cast<size_t>(i)] = read_u16(data, desc_start + vc_off + static_cast<size_t>(i) * 2u);
                desc.index_counts[static_cast<size_t>(i)] = read_u32(data, desc_start + ic_off + static_cast<size_t>(i) * 4u);
            }
        } catch (...) {
            return;
        }
        bool any_vertices = false;
        for (std::uint32_t count : desc.vertex_counts) {
            if (count > 0) any_vertices = true;
            if (count > 200000) return;
        }
        for (std::uint32_t count : desc.index_counts) {
            if (count > 20000000) return;
        }
        if (!any_vertices) return;
        auto names = find_descriptor_names(data, region_start, desc_start);
        desc.name = names.first;
        desc.material = names.second;
        desc.stored_lod_count = stored_lod_count;
        desc.descriptor_offset = static_cast<std::uint32_t>(desc_start);
        descriptors.push_back(desc);
    };

    struct PatternSpec {
        std::vector<unsigned char> pattern;
        int lod_count;
        int vc_off;
        int ic_off;
        int reject_prev;
    };
    const std::vector<PatternSpec> specs = {
        {{0x04, 0x00, 0x01, 0x02, 0x03}, 4, 40, 48, -1},
        {{0x03, 0x00, 0x01, 0x01, 0x02}, 3, 40, 46, -1},
        {{0x03, 0x00, 0x01, 0x02}, 3, 40, 46, 0x04},
        {{0x02, 0x00, 0x01}, 2, 40, 44, 0x03},
    };
    for (const PatternSpec& spec : specs) {
        size_t pos = region_start;
        while (true) {
            const int found = find_bytes(data, spec.pattern, pos, region_end);
            if (found < 0) break;
            const size_t idx = static_cast<size_t>(found);
            bool accept = true;
            if (spec.reject_prev >= 0 && idx > region_start) {
                const unsigned char prev = static_cast<unsigned char>(data[idx - 1]);
                if (spec.lod_count == 3) accept = prev != 0x04;
                if (spec.lod_count == 2) accept = prev != 0x03 && prev != 0x04;
            }
            if (accept) append_descriptor(idx, spec.lod_count, spec.vc_off, spec.ic_off);
            pos = idx + spec.pattern.size();
        }
    }
    std::sort(descriptors.begin(), descriptors.end(), [](const PacDescriptor& a, const PacDescriptor& b) {
        return a.descriptor_offset < b.descriptor_offset;
    });
    return descriptors;
}
