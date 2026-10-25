// Reading and writing archive entries the way CDMW's Python does: parse_archive_pamt_bytes,
// read_archive_entry_data and archive_patching's payload processing, for the tables,
// string tables and XML a composition touches. Other formats refuse as Unsupported.
#include "composer_internal.hpp"

#include <fstream>
#include <unordered_set>

namespace cdmw::compose {
using namespace detail;
namespace {

constexpr std::uint32_t no_parent = 0xFFFFFFFF;
constexpr std::size_t text_preview_limit = 240000;  // ARCHIVE_TEXT_PREVIEW_LIMIT

const std::unordered_set<std::string> structured_extensions = {
    ".bnk", ".binarygimmick", ".hkx", ".levelinfo", ".meshinfo", ".motionblending", ".paa", ".pae",
    ".paa_metabin", ".pabgb", ".pabgh", ".pabc", ".pabv", ".papr", ".paccd", ".pamhc", ".pappt", ".paem",
    ".pagbg", ".pamt", ".pampg", ".palevel", ".paseq", ".paseqc", ".paschedule", ".paschedulepath",
    ".pastage", ".uianiminit", ".pamlod", ".prefab", ".roadsector", ".road", ".nav", ".seqmt", ".wem",
    // ARCHIVE_MODEL_EXTENSIONS share the structured-binary check.
    ".3ds", ".dae", ".fbx", ".glb", ".gltf", ".mesh", ".mdl", ".model", ".obj", ".pac", ".pab", ".pam",
    ".pat", ".patx", ".hkt",
};
const std::unordered_set<std::string> xml_like_extensions = {
    ".pami", ".pac_xml", ".pam_xml", ".pamlod_xml", ".xml", ".app_xml", ".prefabdata_xml",
};

std::string ascii_lower(std::string text) {
    for (auto& c : text) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return text;
}

// ArchiveEntry.basename and .extension.
std::string basename_of(const std::string& path) {
    const auto slash = path.find_last_of("/\\");
    return slash == std::string::npos ? path : path.substr(slash + 1);
}
std::string extension_of(const std::string& path) {
    const auto slash = path.find_last_of("/\\"), dot = path.rfind('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot <= slash)) return "";
    return ascii_lower(path.substr(dot));
}

std::string strip(const std::string& text, std::string_view chars) {
    const auto first = text.find_first_not_of(chars);
    if (first == std::string::npos) return "";
    return text.substr(first, text.find_last_not_of(chars) - first + 1);
}

// bytes.decode("utf-8", errors="replace"): each maximal ill-formed subsequence becomes one
// U+FFFD, as CPython's decoder emits them.
std::u32string decode_replace(const std::uint8_t* data, std::size_t size, std::size_t limit = SIZE_MAX) {
    std::u32string out;
    std::size_t at = 0;
    const auto in = [&](std::size_t offset, std::uint8_t low, std::uint8_t high) {
        return at + offset < size && data[at + offset] >= low && data[at + offset] <= high;
    };
    while (at < size && out.size() < limit) {
        const auto lead = data[at];
        std::size_t length = 0, valid = 0;
        std::uint8_t low = 0x80, high = 0xBF;
        if (lead < 0x80) { out.push_back(lead); ++at; continue; }
        if (lead >= 0xC2 && lead <= 0xDF) length = 2;
        else if (lead >= 0xE0 && lead <= 0xEF) { length = 3; low = lead == 0xE0 ? 0xA0 : 0x80; high = lead == 0xED ? 0x9F : 0xBF; }
        else if (lead >= 0xF0 && lead <= 0xF4) { length = 4; low = lead == 0xF0 ? 0x90 : 0x80; high = lead == 0xF4 ? 0x8F : 0xBF; }
        if (length) {
            valid = 1;
            if (in(1, low, high)) {
                valid = 2;
                while (valid < length && in(valid, 0x80, 0xBF)) ++valid;
            }
        }
        if (!length || valid < length) {
            out.push_back(0xFFFD);
            at += std::max<std::size_t>(valid, 1);
            continue;
        }
        char32_t code = lead & (0x7Fu >> length);
        for (std::size_t i = 1; i < length; ++i) code = (code << 6) | (data[at + i] & 0x3Fu);
        out.push_back(code);
        at += length;
    }
    return out;
}

std::string encode_utf8(const std::u32string& text) {
    std::string out;
    for (const auto c : text) {
        if (c < 0x80) out += static_cast<char>(c);
        else if (c < 0x800) { out += static_cast<char>(0xC0 | (c >> 6)); out += static_cast<char>(0x80 | (c & 0x3F)); }
        else if (c < 0x10000) { out += static_cast<char>(0xE0 | (c >> 12)); out += static_cast<char>(0x80 | ((c >> 6) & 0x3F)); out += static_cast<char>(0x80 | (c & 0x3F)); }
        else { out += static_cast<char>(0xF0 | (c >> 18)); out += static_cast<char>(0x80 | ((c >> 12) & 0x3F)); out += static_cast<char>(0x80 | ((c >> 6) & 0x3F)); out += static_cast<char>(0x80 | (c & 0x3F)); }
    }
    return out;
}

// str.isspace()
bool python_space(char32_t c) {
    return c == ' ' || (c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x1F) || c == 0x85 || c == 0xA0 || c == 0x1680 ||
           (c >= 0x2000 && c <= 0x200A) || c == 0x2028 || c == 0x2029 || c == 0x202F || c == 0x205F || c == 0x3000;
}

// VfsPathResolver: a name block is a trie of (u32 parent, u8 length, bytes) records.
class NameResolver {
public:
    NameResolver(const Bytes& block, std::size_t max_cache) : block_(block), max_cache_(max_cache) {}

    std::string get(std::uint32_t offset) {
        if (offset == no_parent || offset >= block_.size()) return "";
        if (const auto cached = cache_.find(offset); cached != cache_.end()) return cached->second;
        std::vector<std::pair<std::uint32_t, std::string>> parts;
        std::uint32_t current = offset;
        std::string base;
        std::set<std::uint32_t> seen;
        while (current != no_parent) {
            if (!seen.insert(current).second) break;
            if (const auto cached = cache_.find(current); cached != cache_.end()) {
                base = cached->second;
                break;
            }
            const std::size_t at = current;
            if (at + 5 > block_.size()) break;
            const auto parent = u32(block_, at);
            const std::size_t length = block_[at + 4];
            if (at + 5 + length > block_.size()) break;
            parts.emplace_back(current, encode_utf8(decode_replace(block_.data() + at + 5, length)));
            current = parent;
            if (parts.size() > 255) break;
        }
        auto built = base;
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
            built += it->second;
            // The Python cache starts with the root entry, which counts against its size.
            if (cache_.size() + 1 < max_cache_) cache_[it->first] = built;
        }
        const auto cached = cache_.find(offset);
        return cached != cache_.end() ? cached->second : built;
    }

private:
    const Bytes& block_;
    std::size_t max_cache_;
    std::unordered_map<std::uint32_t, std::string> cache_;
};

std::string tidy(const std::string& path) { return strip(replace_all(path, "\\", "/"), "/"); }

Bytes read_raw(const ArchiveEntry& entry) {
    std::error_code error;
    if (!std::filesystem::exists(entry.paz_path, error)) throw FormatError("Missing PAZ file: " + utf8_of(entry.paz_path));
    std::ifstream stream(entry.paz_path, std::ios::binary);
    if (!stream) throw FormatError("could not open " + utf8_of(entry.paz_path));
    stream.seekg(0, std::ios::end);
    const auto size = static_cast<std::uint64_t>(stream.tellg());
    // Python reads what is there: a short read is not an error by itself.
    const std::uint64_t wanted = entry.stored_size != entry.orig_size ? entry.stored_size : entry.orig_size;
    const std::uint64_t available = entry.offset >= size ? 0 : std::min<std::uint64_t>(wanted, size - entry.offset);
    if (available > (1ull << 31)) throw Unsupported("archive entry is too large to compose");
    Bytes data(static_cast<std::size_t>(available));
    if (available) {
        stream.seekg(static_cast<std::streamoff>(entry.offset));
        stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(available));
        if (static_cast<std::uint64_t>(stream.gcount()) != available) throw FormatError("short read from " + utf8_of(entry.paz_path));
    }
    return data;
}

}  // namespace

namespace detail {

// archive_format's try_decode_text_like_archive_data(data) is not None.
bool text_like(const Bytes& data) {
    if (data.empty()) return false;
    const std::size_t preview = std::min(data.size(), text_preview_limit);
    const auto stripped_nonempty = [](const std::u32string& text) {
        return std::any_of(text.begin(), text.end(), [](char32_t c) { return c != 0xFEFF && c != '\r' && c != '\n' && c != '\t' && c != ' '; });
    };
    if (starts_with(data, "\xEF\xBB\xBF")) return stripped_nonempty(decode_replace(data.data() + 3, preview - 3));
    if (starts_with(data, "\xFF\xFE") || starts_with(data, "\xFE\xFF")) {
        // Every surrogate, lone or paired, and a trailing odd byte decode to something kept.
        const bool little = data[0] == 0xFF;
        if (preview % 2) return true;
        for (std::size_t at = 0; at + 1 < preview; at += 2) {
            const unsigned unit = little ? data[at] | (data[at + 1] << 8) : (data[at] << 8) | data[at + 1];
            if (unit != 0xFEFF && unit != '\r' && unit != '\n' && unit != '\t' && unit != ' ') return true;
        }
        return false;
    }
    const std::size_t sample = std::min<std::size_t>(preview, 4096);
    const auto zeros = static_cast<std::size_t>(std::count(data.begin(), data.begin() + static_cast<std::ptrdiff_t>(sample), 0));
    if (zeros > std::max<std::size_t>(2, sample / 100)) return false;
    const auto printable = static_cast<std::size_t>(std::count_if(data.begin(), data.begin() + static_cast<std::ptrdiff_t>(sample),
        [](std::uint8_t v) { return v == 9 || v == 10 || v == 13 || (v >= 32 && v <= 126); }));
    std::size_t lead = 0;
    while (lead < sample && (data[lead] == 0xEF || data[lead] == 0xBB || data[lead] == 0xBF || data[lead] == '\r' ||
                             data[lead] == '\n' || data[lead] == '\t' || data[lead] == ' ')) ++lead;
    const bool markup = lead < sample && (data[lead] == '<' || data[lead] == '{' || data[lead] == '[');
    // printable / len(sample) < 0.92, exactly: the ratio never sits within a double's
    // rounding of 23/25 for a sample of at most 4096 bytes.
    if (printable * 25 < sample * 23 && !markup) return false;
    const auto text = decode_replace(data.data(), preview, 1024);
    std::size_t visible = 0, controls = 0;
    for (const auto c : text) {
        if (python_space(c)) continue;
        ++visible;
        if (c < 32) ++controls;
    }
    if (!visible) return false;
    return controls <= std::max<std::size_t>(2, visible / 20);
}

}  // namespace detail

std::string normalize_game_path(const std::string& path) {
    return ascii_lower(strip(strip(replace_all(path, "\\", "/"), " \t\n\r\v\f\x1c\x1d\x1e\x1f"), "/"));
}

Bytes crypt_chacha20(const Bytes& data, const std::string& filename) {
    const auto name = basename_of(filename);
    if (std::any_of(name.begin(), name.end(), [](char c) { return static_cast<unsigned char>(c) >= 0x80; }))
        throw Unsupported("ChaCha20 keys for non-ASCII file names follow Python's Unicode case folding");
    const auto lowered = ascii_lower(name);
    const auto seed = hashlittle(reinterpret_cast<const std::uint8_t*>(lowered.data()), lowered.size(), 0x000C5EDE);
    const std::uint32_t key = seed ^ 0x60616263u;
    constexpr std::uint32_t deltas[8] = {0x00000000u, 0x0A0A0A0Au, 0x0C0C0C0Cu, 0x06060606u,
                                         0x0E0E0E0Eu, 0x0A0A0A0Au, 0x06060606u, 0x02020202u};
    std::array<std::uint32_t, 16> state = {0x61707865u, 0x3320646Eu, 0x79622D32u, 0x6B206574u};
    for (int i = 0; i < 8; ++i) state[4 + i] = key ^ deltas[i];
    state[12] = state[13] = state[14] = state[15] = seed;  // a 32-bit counter, then the nonce
    // The cryptography package refuses a payload whose block counter would pass 2^32.
    if (std::uint64_t(seed) + (std::uint64_t(data.size()) + 63) / 64 > (std::uint64_t(1) << 32))
        throw FormatError("Exceeded the maximum number of bytes that can be encrypted with ChaCha20 for this nonce.");
    const auto rotate = [](std::uint32_t v, int s) { return (v << s) | (v >> (32 - s)); };
    const auto quarter = [&](std::array<std::uint32_t, 16>& x, int a, int b, int c, int d) {
        x[a] += x[b]; x[d] ^= x[a]; x[d] = rotate(x[d], 16);
        x[c] += x[d]; x[b] ^= x[c]; x[b] = rotate(x[b], 12);
        x[a] += x[b]; x[d] ^= x[a]; x[d] = rotate(x[d], 8);
        x[c] += x[d]; x[b] ^= x[c]; x[b] = rotate(x[b], 7);
    };
    Bytes out(data.size());
    for (std::size_t offset = 0; offset < data.size(); offset += 64) {
        auto x = state;
        for (int round = 0; round < 10; ++round) {
            quarter(x, 0, 4, 8, 12); quarter(x, 1, 5, 9, 13); quarter(x, 2, 6, 10, 14); quarter(x, 3, 7, 11, 15);
            quarter(x, 0, 5, 10, 15); quarter(x, 1, 6, 11, 12); quarter(x, 2, 7, 8, 13); quarter(x, 3, 4, 9, 14);
        }
        for (std::size_t i = 0; i < 64 && offset + i < data.size(); ++i) {
            const auto word = x[i / 4] + state[i / 4];
            out[offset + i] = static_cast<std::uint8_t>(data[offset + i] ^ static_cast<std::uint8_t>(word >> (8 * (i % 4))));
        }
        ++state[12];
    }
    return out;
}

Bytes stored_payload(const Bytes& data, std::uint64_t flags, const std::string& basename) {
    const auto compression = flags & 15;
    if (compression > 2) throw FormatError("Archive patching does not support compression type " + std::to_string(compression) + " yet.");
    auto stored = compression == 2 ? lz4::compress(data.data(), data.size()) : data;
    return flags >> 4 ? crypt_chacha20(stored, basename) : stored;
}

std::vector<ArchiveEntry> parse_pamt(const Bytes& data, const std::filesystem::path& pamt_path) {
    const auto name = utf8_of(pamt_path.filename());
    const auto need = [&](std::uint64_t end, const char* what) {
        if (end > data.size()) throw FormatError(name + " " + what + " is truncated.");
    };
    if (data.size() < 12) throw FormatError(utf8_of(pamt_path) + " is too small to be a valid .pamt file.");
    const std::uint64_t paz_count = u32(data, 4);
    std::uint64_t at = 12 + paz_count * 12;
    need(at, "paz table");
    const auto block = [&](const char* what) {
        need(at + 4, what);
        const std::uint64_t size = u32(data, static_cast<std::size_t>(at));
        at += 4;
        need(at + size, what);
        auto value = slice(data, static_cast<std::size_t>(at), static_cast<std::size_t>(at + size));
        at += size;
        return value;
    };
    const auto directories = block("directory block");
    const auto names = block("file-name block");
    need(at + 4, "folder table length");
    const std::uint64_t folder_count = u32(data, static_cast<std::size_t>(at));
    at += 4;
    need(at + folder_count * 16, "folder table");
    const auto folders_at = static_cast<std::size_t>(at);
    at += folder_count * 16;
    need(at + 4, "file table length");
    const std::uint64_t file_count = u32(data, static_cast<std::size_t>(at));
    at += 4;
    need(at + file_count * 20, "file table");
    const auto files_at = static_cast<std::size_t>(at);

    NameResolver file_names(names, 200000), folder_names(directories, 50000);
    std::vector<std::tuple<std::uint64_t, std::uint64_t, std::string>> ranges;
    for (std::size_t i = 0; i < folder_count; ++i) {
        const auto row = folders_at + i * 16;
        const std::uint64_t start = u32(data, row + 8), count = u32(data, row + 12);
        if (count > 0) ranges.emplace_back(start, start + count, tidy(folder_names.get(u32(data, row + 4))));
    }
    std::sort(ranges.begin(), ranges.end());
    const auto folder = pamt_path.parent_path();
    std::vector<ArchiveEntry> entries;
    std::size_t cursor = 0;
    for (std::size_t index = 0; index < file_count; ++index) {
        const auto row = files_at + index * 20;
        const auto relative = tidy(file_names.get(u32(data, row)));
        std::string directory;
        while (cursor < ranges.size() && index >= std::get<1>(ranges[cursor])) ++cursor;
        if (cursor < ranges.size() && std::get<0>(ranges[cursor]) <= index && index < std::get<1>(ranges[cursor]))
            directory = std::get<2>(ranges[cursor]);
        ArchiveEntry entry;
        entry.path = directory.empty() ? relative : strip(directory + "/" + relative, "/");
        entry.pamt_path = pamt_path;
        entry.offset = u32(data, row + 4);
        entry.stored_size = u32(data, row + 8);
        entry.orig_size = u32(data, row + 12);
        entry.paz_index = u16(data, row + 16);
        entry.flags = u16(data, row + 18);
        if (entry.paz_index >= paz_count) throw FormatError("Invalid PAZ index " + std::to_string(entry.paz_index) + " for " + utf8_of(pamt_path));
        entry.paz_path = folder / path_of(std::to_string(entry.paz_index) + ".paz");
        entries.push_back(std::move(entry));
    }
    return entries;
}

Bytes read_entry(const ArchiveEntry& entry) {
    const auto extension = extension_of(entry.path);
    const auto basename = basename_of(entry.path);
    const auto compression = entry.flags & 15u;
    const bool dds = extension == ".dds";
    auto data = read_raw(entry);
    const auto expand = [&](const Bytes& block) { return lz4::decompress_upto(block.data(), block.size(), static_cast<std::size_t>(entry.orig_size)); };
    if (entry.flags >> 4) {
        if (((entry.flags >> 4) & 15u) != 3) throw FormatError("Unsupported archive encryption type for " + entry.path);
        auto candidate = crypt_chacha20(data, basename);
        if (extension == ".paloc") {
            parse_paloc(compression == 2 ? expand(candidate) : candidate);
            data = std::move(candidate);
        } else {
            // _looks_like_decrypted_payload
            const auto plausible = [&](const Bytes& payload) {
                if (dds) throw Unsupported("encrypted DDS entries are not composed");
                Bytes decoded;
                const Bytes* view = &payload;
                if (compression == 2) {
                    try {
                        decoded = expand(payload);
                    } catch (const FormatError&) {
                        return false;
                    }
                    view = &decoded;
                }
                if (text_like(*view)) return true;
                if (structured_extensions.count(extension)) throw Unsupported("the structured-binary decryption check is not ported");
                return false;
            };
            if (plausible(candidate)) data = std::move(candidate);
            else if (!(xml_like_extensions.count(extension) && plausible(data)))  // a flag that names no cipher
                throw FormatError("ChaCha20 decryption validation failed for " + entry.path);
        }
    }
    if (entry.stored_size != entry.orig_size) {
        if (dds) throw Unsupported("DDS entries are not composed");
        if (compression == 1) {
            if (data.size() >= 0x50 && (extension == ".pamlod" || starts_with(data, "PAR ")))
                throw Unsupported("partial PAR containers are not composed");
        } else if (compression == 2) {
            data = expand(data);
        } else {
            throw FormatError("Unsupported archive compression type " + std::to_string(compression) + " for " + entry.path);
        }
    }
    return data;
}

MountedArchives::MountedArchives(const std::filesystem::path& root, const Bytes& papgt) {
    std::set<std::string> listed;
    for (const auto& directory : parse_papgt(papgt)) {
        if (!listed.insert(ascii_lower(directory.name)).second) throw Unsupported("the mount list names a directory twice");
        groups_.push_back(directory.name);
    }
    for (const auto& group : groups_) {
        const auto pamt = root / path_of(group) / "0.pamt";
        std::error_code error;
        if (!std::filesystem::is_regular_file(pamt, error)) continue;
        std::ifstream stream(pamt, std::ios::binary);
        const Bytes data((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
        for (auto& entry : parse_pamt(data, pamt)) {
            first_.emplace(normalize_game_path(entry.path), entries_.size());
            entries_.push_back(std::move(entry));
        }
    }
}

const ArchiveEntry* MountedArchives::find(const std::string& path) const {
    const auto found = first_.find(normalize_game_path(path));
    return found == first_.end() ? nullptr : &entries_[found->second];
}

}  // namespace cdmw::compose
