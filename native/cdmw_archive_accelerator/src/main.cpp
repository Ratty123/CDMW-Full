#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr int kProtocol = 1;
constexpr const char* kBackend = "cdmw_archive_accelerator_0.1";

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 8);
    for (char ch : value) {
        switch (ch) {
        case '\\': out += "\\\\"; break;
        case '"': out += "\\\""; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20) out += ' ';
            else out += ch;
            break;
        }
    }
    return out;
}

std::string read_text(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("could not open " + path.string());
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

std::vector<char> read_binary(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("could not open " + path.string());
    return std::vector<char>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

std::vector<char> read_binary_if_exists(const fs::path& path) {
    if (path.empty() || !fs::is_regular_file(path)) return {};
    return read_binary(path);
}

void write_text(const fs::path& path, const std::string& text) {
    if (!path.parent_path().empty()) fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("could not write " + path.string());
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
}

std::string find_string_value(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return {};
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) return {};
    std::string out;
    bool escaped = false;
    for (size_t i = pos + 1; i < json.size(); ++i) {
        const char ch = json[i];
        if (escaped) {
            switch (ch) {
            case 'n': out += '\n'; break;
            case 'r': out += '\r'; break;
            case 't': out += '\t'; break;
            default: out += ch; break;
            }
            escaped = false;
        } else if (ch == '\\') {
            escaped = true;
        } else if (ch == '"') {
            break;
        } else {
            out += ch;
        }
    }
    return out;
}

bool find_bool_value(const std::string& json, const std::string& key, bool fallback = false) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return fallback;
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    if (json.compare(pos, 4, "true") == 0) return true;
    if (json.compare(pos, 5, "false") == 0) return false;
    return fallback;
}

long long find_int_value(const std::string& json, const std::string& key, long long fallback = 0) {
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return fallback;
    ++pos;
    while (pos < json.size() && std::isspace(static_cast<unsigned char>(json[pos]))) ++pos;
    bool neg = false;
    if (pos < json.size() && json[pos] == '-') {
        neg = true;
        ++pos;
    }
    long long value = 0;
    bool any = false;
    while (pos < json.size() && std::isdigit(static_cast<unsigned char>(json[pos]))) {
        any = true;
        value = value * 10 + (json[pos] - '0');
        ++pos;
    }
    return any ? (neg ? -value : value) : fallback;
}

std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

std::string slash_copy(std::string value) {
    std::replace(value.begin(), value.end(), '\\', '/');
    return value;
}

std::string path_text(const fs::path& path) {
    return path.string();
}

std::uint32_t read_u32(const std::vector<char>& data, size_t offset) {
    if (offset + 4 > data.size()) throw std::runtime_error("u32 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint32_t>(p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24));
}

std::uint16_t read_u16(const std::vector<char>& data, size_t offset) {
    if (offset + 2 > data.size()) throw std::runtime_error("u16 read outside buffer");
    const auto* p = reinterpret_cast<const unsigned char*>(data.data() + offset);
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

std::uint32_t rot32(std::uint32_t value, int shift) {
    return (value << shift) | (value >> (32 - shift));
}

std::uint32_t hashlittle_bytes(const std::string& text, std::uint32_t initval = 0) {
    const auto* data = reinterpret_cast<const unsigned char*>(text.data());
    const size_t length = text.size();
    size_t remaining = length;
    std::uint32_t a = 0xDEADBEEF + static_cast<std::uint32_t>(length) + initval;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    auto read_tail = [&](size_t pos) -> std::uint32_t {
        std::uint32_t value = 0;
        for (size_t i = 0; i < 4 && pos + i < length; ++i) value |= static_cast<std::uint32_t>(data[pos + i]) << (8 * i);
        return value;
    };
    while (remaining > 12) {
        a += read_tail(offset);
        b += read_tail(offset + 4);
        c += read_tail(offset + 8);
        a -= c; a ^= rot32(c, 4); c += b;
        b -= a; b ^= rot32(a, 6); a += c;
        c -= b; c ^= rot32(b, 8); b += a;
        a -= c; a ^= rot32(c, 16); c += b;
        b -= a; b ^= rot32(a, 19); a += c;
        c -= b; c ^= rot32(b, 4); b += a;
        offset += 12;
        remaining -= 12;
    }
    if (remaining >= 9) c += read_tail(offset + 8);
    if (remaining >= 5) b += read_tail(offset + 4);
    if (remaining >= 1) a += read_tail(offset);
    if (remaining == 0) return c;
    c = (c ^ b) - rot32(b, 14);
    a = (a ^ c) - rot32(c, 11);
    b = (b ^ a) - rot32(a, 25);
    c = (c ^ b) - rot32(b, 16);
    a = (a ^ c) - rot32(c, 4);
    b = (b ^ a) - rot32(a, 14);
    c = (c ^ b) - rot32(b, 24);
    return c;
}

class VfsPathResolver {
public:
    explicit VfsPathResolver(std::vector<char> data, size_t max_cache_entries = 200000)
        : data_(std::move(data)), max_cache_entries_(max_cache_entries) {}

    std::string full_path(std::uint32_t offset) {
        if (offset >= data_.size()) return {};
        auto cached = cache_.find(offset);
        if (cached != cache_.end()) return cached->second;
        std::vector<std::pair<std::uint32_t, std::string>> parts;
        std::set<std::uint32_t> seen;
        std::uint32_t current = offset;
        std::string base;
        while (current < data_.size()) {
            if (seen.count(current)) break;
            seen.insert(current);
            auto parent_cached = cache_.find(current);
            if (parent_cached != cache_.end()) {
                base = parent_cached->second;
                break;
            }
            const size_t pos = static_cast<size_t>(current);
            if (pos + 5 > data_.size()) break;
            const std::uint32_t parent = read_u32(data_, pos);
            const auto part_len = static_cast<unsigned char>(data_[pos + 4]);
            if (pos + 5 + part_len > data_.size()) break;
            std::string part(data_.begin() + static_cast<std::ptrdiff_t>(pos + 5), data_.begin() + static_cast<std::ptrdiff_t>(pos + 5 + part_len));
            parts.emplace_back(current, part);
            current = parent;
            if (parts.size() > 255) break;
        }
        std::string built = base;
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
            built += it->second;
            if (cache_.size() < max_cache_entries_) cache_[it->first] = built;
        }
        auto result = cache_.find(offset);
        return result != cache_.end() ? result->second : built;
    }

private:
    std::vector<char> data_;
    size_t max_cache_entries_;
    std::unordered_map<std::uint32_t, std::string> cache_;
};

struct Entry {
    int source_index = 0;
    std::string path;
    fs::path pamt_path;
    fs::path paz_file;
    std::uint32_t offset = 0;
    std::uint32_t comp_size = 0;
    std::uint32_t orig_size = 0;
    std::uint16_t flags = 0;
    std::uint16_t paz_index = 0;
};

std::string extension_for(const std::string& path) {
    const size_t slash = path.find_last_of("/\\");
    const size_t dot = path.find_last_of('.');
    if (dot == std::string::npos || (slash != std::string::npos && dot <= slash)) return {};
    return lower_copy(path.substr(dot));
}

std::string basename_for(const std::string& path) {
    const size_t slash = path.find_last_of("/\\");
    return slash == std::string::npos ? path : path.substr(slash + 1);
}

int slash_depth_for(const std::string& path) {
    return static_cast<int>(std::count(path.begin(), path.end(), '/'));
}

std::string package_label_for(const Entry& entry) {
    return entry.pamt_path.parent_path().filename().string() + "/" + entry.pamt_path.filename().string();
}

std::vector<std::string> split_parts(const std::string& text) {
    std::vector<std::string> parts;
    std::stringstream stream(text);
    std::string part;
    while (std::getline(stream, part, '/')) {
        if (!part.empty() && part != "." && part != "..") parts.push_back(part);
    }
    return parts;
}

std::string key_join(const std::vector<std::string>& parts, size_t count) {
    std::string out;
    for (size_t i = 0; i < count && i < parts.size(); ++i) {
        if (!out.empty()) out += "/";
        out += parts[i];
    }
    return out;
}

std::vector<std::string> folder_parts_for_tree(const Entry& entry) {
    std::string normalized = slash_copy(entry.path);
    const size_t slash = normalized.find_last_of('/');
    if (slash == std::string::npos) return {};
    return split_parts(normalized.substr(0, slash));
}

std::vector<std::string> structure_parts_for(const Entry& entry) {
    std::vector<std::string> parts;
    std::string package = lower_copy(entry.pamt_path.parent_path().filename().string());
    parts.push_back(package.empty() ? "package" : package);
    std::string normalized = lower_copy(slash_copy(entry.path));
    const size_t slash = normalized.find_last_of('/');
    if (slash != std::string::npos) {
        std::vector<std::string> folders = split_parts(normalized.substr(0, slash));
        parts.insert(parts.end(), folders.begin(), folders.end());
    }
    return parts;
}

bool is_previewable_ext(const std::string& ext) {
    static const std::set<std::string> exts = {
        ".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".webp",
        ".wem", ".bnk", ".wav", ".mp4", ".xml", ".json", ".cfg", ".lua", ".txt",
        ".pam", ".pamlod", ".pac", ".pathc", ".hkx", ".hkt", ".meshinfo", ".prefab", ".pappt", ".pamhc"
    };
    return exts.count(ext) != 0;
}

std::string normalize_extension(std::string ext) {
    ext = lower_copy(ext);
    if (ext.empty() || ext == "*" || ext == "all" || ext == ".*") return ext;
    return ext[0] == '.' ? ext : "." + ext;
}

std::string stem_for_path(const std::string& path) {
    std::string base = basename_for(slash_copy(path));
    const size_t dot = base.find_last_of('.');
    if (dot != std::string::npos) base = base.substr(0, dot);
    return lower_copy(base);
}

std::string package_group_for(const Entry& entry) {
    return lower_copy(entry.pamt_path.parent_path().filename().string());
}

bool starts_with(const std::string& text, const std::string& prefix) {
    return text.rfind(prefix, 0) == 0;
}

std::string strip_model_variant_suffix(std::string stem) {
    stem = lower_copy(stem);
    static const std::vector<std::string> suffixes = {
        "_index01_l", "_index01_r", "_index02_l", "_index02_r", "_index03_l", "_index03_r",
        "_index01", "_index02", "_index03", "_sub01", "_sub02", "_sub03", "_l", "_r", "_u", "_s", "_t", "_c", "_d"
    };
    bool changed = true;
    while (changed) {
        changed = false;
        for (const std::string& suffix : suffixes) {
            if (
                stem.size() > suffix.size()
                && std::equal(suffix.rbegin(), suffix.rend(), stem.rbegin())
            ) {
                stem.resize(stem.size() - suffix.size());
                changed = true;
                break;
            }
        }
    }
    if (stem.size() >= 2 && std::isdigit(static_cast<unsigned char>(stem[stem.size() - 2])) && std::isalpha(static_cast<unsigned char>(stem.back()))) {
        stem.pop_back();
    }
    return stem;
}

std::vector<std::string> model_candidate_bases(const std::string& stem) {
    std::vector<std::string> out;
    std::set<std::string> seen;
    auto add = [&](std::string value) {
        value = lower_copy(value);
        if (!value.empty() && !seen.count(value)) {
            seen.insert(value);
            out.push_back(value);
        }
    };
    add(stem);
    add(strip_model_variant_suffix(stem));
    return out;
}

bool ends_with(const std::string& text, const std::string& suffix) {
    return suffix.size() <= text.size() && std::equal(suffix.rbegin(), suffix.rend(), text.rbegin());
}

bool common_technical_suffix(const std::string& path_lower) {
    static const std::vector<std::string> suffixes = {
        "_n.dds", "_nm.dds", "_nrm.dds", "_normal.dds", "_normalmap.dds", "_sp.dds", "_spec.dds",
        "_specular.dds", "_m.dds", "_mask.dds", "_orm.dds", "_rma.dds", "_mra.dds", "_arm.dds",
        "_ao.dds", "_metal.dds", "_metallic.dds", "_rough.dds", "_roughness.dds", "_gloss.dds",
        "_smooth.dds", "_height.dds", "_hgt.dds", "_disp.dds", "_displacement.dds", "_dmap.dds",
        "_bump.dds", "_parallax.dds", "_pom.dds", "_ssdm.dds", "_vector.dds", "_dr.dds", "_op.dds",
        "_wn.dds", "_flow.dds", "_velocity.dds", "_pos.dds", "_position.dds", "_pivot.dds",
        "_depth.dds", "_pivotpos.dds", "_ma.dds", "_mg.dds", "_o.dds", "_emi.dds", "_emc.dds",
        "_subsurface.dds", "_1bit.dds", "_mask_amg.dds", "_d.dds"
    };
    for (const std::string& suffix : suffixes) {
        if (ends_with(path_lower, suffix)) return true;
    }
    return false;
}

std::vector<Entry> parse_pamt(const fs::path& pamt_path) {
    std::vector<char> data = read_binary(pamt_path);
    if (data.size() < 12) throw std::runtime_error(pamt_path.string() + " is too small");
    size_t off = 0;
    (void)read_u32(data, off);
    const std::uint32_t paz_count = read_u32(data, off + 4);
    off += 12;
    off += static_cast<size_t>(paz_count) * 12u;
    if (off + 4 > data.size()) throw std::runtime_error("paz table is truncated");
    const std::uint32_t dir_block_size = read_u32(data, off);
    off += 4;
    if (off + dir_block_size > data.size()) throw std::runtime_error("directory block is truncated");
    std::vector<char> directory(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + dir_block_size));
    off += dir_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("file-name block length is truncated");
    const std::uint32_t file_name_block_size = read_u32(data, off);
    off += 4;
    if (off + file_name_block_size > data.size()) throw std::runtime_error("file-name block is truncated");
    std::vector<char> file_names(data.begin() + static_cast<std::ptrdiff_t>(off), data.begin() + static_cast<std::ptrdiff_t>(off + file_name_block_size));
    off += file_name_block_size;
    if (off + 4 > data.size()) throw std::runtime_error("folder table length is truncated");
    const std::uint32_t folder_count = read_u32(data, off);
    off += 4;
    const size_t folder_table_offset = off;
    off += static_cast<size_t>(folder_count) * 16u;
    if (off + 4 > data.size()) throw std::runtime_error("file table length is truncated");
    const std::uint32_t file_count = read_u32(data, off);
    off += 4;
    const size_t file_table_offset = off;
    if (off + static_cast<size_t>(file_count) * 20u > data.size()) throw std::runtime_error("file table is truncated");

    VfsPathResolver file_resolver(std::move(file_names));
    VfsPathResolver dir_resolver(std::move(directory), 50000);
    struct FolderRange { std::uint32_t start; std::uint32_t end; std::string dir; };
    std::vector<FolderRange> ranges;
    for (std::uint32_t i = 0; i < folder_count; ++i) {
        const size_t row = folder_table_offset + static_cast<size_t>(i) * 16u;
        const std::uint32_t name_offset = read_u32(data, row + 4);
        const std::uint32_t file_start = read_u32(data, row + 8);
        const std::uint32_t count = read_u32(data, row + 12);
        if (count == 0) continue;
        ranges.push_back({file_start, file_start + count, slash_copy(dir_resolver.full_path(name_offset))});
    }
    std::sort(ranges.begin(), ranges.end(), [](const FolderRange& a, const FolderRange& b) { return a.start < b.start; });
    std::vector<fs::path> paz_files;
    for (std::uint32_t i = 0; i < paz_count; ++i) paz_files.push_back(pamt_path.parent_path() / (std::to_string(i) + ".paz"));
    std::vector<Entry> entries;
    entries.reserve(file_count);
    size_t folder_cursor = 0;
    for (std::uint32_t i = 0; i < file_count; ++i) {
        const size_t row = file_table_offset + static_cast<size_t>(i) * 20u;
        const std::uint32_t name_offset = read_u32(data, row);
        Entry entry;
        entry.path = slash_copy(file_resolver.full_path(name_offset));
        while (folder_cursor < ranges.size() && i >= ranges[folder_cursor].end) ++folder_cursor;
        if (folder_cursor < ranges.size() && i >= ranges[folder_cursor].start && i < ranges[folder_cursor].end && !ranges[folder_cursor].dir.empty()) {
            entry.path = ranges[folder_cursor].dir + "/" + entry.path;
        }
        entry.pamt_path = pamt_path;
        entry.offset = read_u32(data, row + 4);
        entry.comp_size = read_u32(data, row + 8);
        entry.orig_size = read_u32(data, row + 12);
        entry.paz_index = read_u16(data, row + 16);
        entry.flags = read_u16(data, row + 18);
        if (entry.paz_index >= paz_files.size()) throw std::runtime_error("invalid paz index");
        entry.paz_file = paz_files[entry.paz_index];
        entries.push_back(std::move(entry));
    }
    return entries;
}

std::vector<Entry> scan_package_root(const fs::path& package_root) {
    std::vector<fs::path> pamt_files;
    if (fs::is_regular_file(package_root) && lower_copy(package_root.extension().string()) == ".pamt") {
        pamt_files.push_back(package_root);
    } else {
        for (fs::recursive_directory_iterator it(package_root), end; it != end; ++it) {
            const fs::directory_entry& item = *it;
            if (it.depth() == 0 && item.is_directory() && lower_copy(item.path().filename().string()) == "cdmods") {
                it.disable_recursion_pending();
                continue;
            }
            if (item.is_regular_file() && lower_copy(item.path().extension().string()) == ".pamt") pamt_files.push_back(item.path());
        }
    }
    if (pamt_files.empty()) throw std::runtime_error("no .pamt files were found under " + package_root.string());
    std::sort(pamt_files.begin(), pamt_files.end());
    std::vector<Entry> all;
    for (const fs::path& pamt : pamt_files) {
        std::vector<Entry> entries = parse_pamt(pamt);
        all.insert(all.end(), std::make_move_iterator(entries.begin()), std::make_move_iterator(entries.end()));
    }
    return all;
}

std::string entries_json(const std::vector<Entry>& entries) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"" << kBackend << "\",\"protocol\":" << kProtocol
        << ",\"entry_count\":" << entries.size() << ",\"entries\":[";
    for (size_t i = 0; i < entries.size(); ++i) {
        const Entry& e = entries[i];
        if (i) out << ",";
        out << "{\"path\":\"" << json_escape(e.path)
            << "\",\"pamt_path\":\"" << json_escape(path_text(e.pamt_path))
            << "\",\"paz_file\":\"" << json_escape(path_text(e.paz_file))
            << "\",\"offset\":" << e.offset
            << ",\"comp_size\":" << e.comp_size
            << ",\"orig_size\":" << e.orig_size
            << ",\"flags\":" << e.flags
            << ",\"paz_index\":" << e.paz_index << "}";
    }
    out << "]}";
    return out.str();
}

std::vector<std::string> split_tsv(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, '\t')) fields.push_back(field);
    return fields;
}

std::vector<Entry> read_entries_tsv(const fs::path& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("could not open entries TSV");
    std::vector<Entry> entries;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        std::vector<std::string> f = split_tsv(line);
        if (f.size() < 9) continue;
        Entry e;
        e.source_index = std::stoi(f[0]);
        e.path = f[1];
        e.pamt_path = fs::path(f[2]);
        e.paz_file = fs::path(f[3]);
        e.offset = static_cast<std::uint32_t>(std::stoul(f[4]));
        e.comp_size = static_cast<std::uint32_t>(std::stoul(f[5]));
        e.orig_size = static_cast<std::uint32_t>(std::stoul(f[6]));
        e.flags = static_cast<std::uint16_t>(std::stoul(f[7]));
        e.paz_index = static_cast<std::uint16_t>(std::stoul(f[8]));
        entries.push_back(std::move(e));
    }
    return entries;
}

void write_progress_json(const fs::path& path, const std::string& stage, long long current, long long total) {
    if (path.empty()) return;
    std::ostringstream out;
    out << "{\"stage\":\"" << json_escape(stage) << "\",\"current\":" << current << ",\"total\":" << total << "}";
    try {
        write_text(path, out.str());
    } catch (...) {
    }
}

struct BrowserOptions {
    std::string filter_text;
    std::string exclude_filter_text;
    std::string extension_filter = "*";
    std::string package_filter_text;
    std::string structure_filter;
    bool exclude_common_technical_suffixes = false;
    int min_size_kb = 0;
    bool previewable_only = false;
    bool build_structure_children = true;
    bool build_tree_index = true;
};

bool entry_matches(const Entry& entry, const BrowserOptions& options) {
    const std::string ext = extension_for(entry.path);
    const std::string normalized_ext = normalize_extension(options.extension_filter);
    if (!normalized_ext.empty() && normalized_ext != "*" && normalized_ext != "all" && normalized_ext != ".*" && ext != normalized_ext) return false;
    const std::string path_lower = lower_copy(slash_copy(entry.path));
    const std::string basename_lower = lower_copy(basename_for(entry.path));
    const std::string filter = lower_copy(options.filter_text);
    if (!filter.empty() && path_lower.find(filter) == std::string::npos && basename_lower.find(filter) == std::string::npos) return false;
    const std::string exclude = lower_copy(options.exclude_filter_text);
    if (!exclude.empty() && (path_lower.find(exclude) != std::string::npos || basename_lower.find(exclude) != std::string::npos)) return false;
    if (options.exclude_common_technical_suffixes && common_technical_suffix(path_lower)) return false;
    const std::string package_filter = lower_copy(options.package_filter_text);
    if (!package_filter.empty()) {
        const std::string package_label = lower_copy(package_label_for(entry));
        const std::string pamt_text = lower_copy(path_text(entry.pamt_path));
        if (package_label.find(package_filter) == std::string::npos && pamt_text.find(package_filter) == std::string::npos) return false;
    }
    if (options.min_size_kb > 0 && entry.orig_size < static_cast<std::uint32_t>(options.min_size_kb * 1024)) return false;
    if (options.previewable_only && !is_previewable_ext(ext)) return false;
    const std::string structure_filter = lower_copy(slash_copy(options.structure_filter));
    if (!structure_filter.empty()) {
        std::vector<std::string> parts = structure_parts_for(entry);
        bool matched = false;
        for (size_t i = 1; i <= parts.size(); ++i) {
            if (key_join(parts, i) == structure_filter) {
                matched = true;
                break;
            }
        }
        if (!matched) return false;
    }
    return true;
}

std::string string_array_json(const std::vector<std::string>& key) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < key.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(key[i]) << "\"";
    }
    out << "]";
    return out.str();
}

std::string structure_children_json(const std::vector<Entry>& entries) {
    std::map<std::string, std::map<std::string, int>> child_counts;
    for (const Entry& entry : entries) {
        std::vector<std::string> parts = structure_parts_for(entry);
        std::string parent;
        std::string child;
        for (const std::string& part : parts) {
            child = child.empty() ? part : child + "/" + part;
            child_counts[parent][child] += 1;
            parent = child;
        }
    }
    std::ostringstream out;
    out << "[";
    bool first_parent = true;
    for (const auto& [parent, children] : child_counts) {
        if (!first_parent) out << ",";
        first_parent = false;
        out << "{\"parent\":\"" << json_escape(parent) << "\",\"children\":[";
        bool first_child = true;
        for (const auto& [child, count] : children) {
            if (!first_child) out << ",";
            first_child = false;
            out << "[\"" << json_escape(child) << "\"," << count << "]";
        }
        out << "]}";
    }
    out << "]";
    return out.str();
}

struct TreeState {
    std::map<std::vector<std::string>, std::map<std::vector<std::string>, std::string>> child_folders;
    std::map<std::vector<std::string>, std::vector<std::pair<std::string, int>>> direct_files;
    std::map<std::vector<std::string>, std::vector<int>> folder_entry_indexes;
    std::map<std::vector<std::string>, std::tuple<int, std::uint64_t, std::uint64_t>> folder_stats;
};

TreeState build_tree(const std::vector<Entry>& filtered) {
    TreeState state;
    for (size_t i = 0; i < filtered.size(); ++i) {
        const Entry& entry = filtered[i];
        const int index = static_cast<int>(i);
        const std::vector<std::string> folder_key = folder_parts_for_tree(entry);
        state.direct_files[folder_key].push_back({lower_copy(basename_for(entry.path)), index});
        state.folder_entry_indexes[{}].push_back(index);
        auto& root_stats = state.folder_stats[{}];
        root_stats = {std::get<0>(root_stats) + 1, std::get<1>(root_stats) + entry.orig_size, std::get<2>(root_stats) + entry.comp_size};
        std::vector<std::string> parent;
        std::vector<std::string> child;
        for (const std::string& part : folder_key) {
            child.push_back(part);
            state.child_folders[parent][child] = part;
            state.folder_entry_indexes[child].push_back(index);
            auto& stats = state.folder_stats[child];
            stats = {std::get<0>(stats) + 1, std::get<1>(stats) + entry.orig_size, std::get<2>(stats) + entry.comp_size};
            parent = child;
        }
    }
    return state;
}

std::string tree_json(const TreeState& state) {
    std::ostringstream out;
    out << "\"tree_child_folders\":[";
    bool first = true;
    for (const auto& [parent, children] : state.child_folders) {
        if (!first) out << ",";
        first = false;
        out << "{\"parent\":" << string_array_json(parent) << ",\"children\":[";
        bool first_child = true;
        for (const auto& [child_key, leaf] : children) {
            if (!first_child) out << ",";
            first_child = false;
            out << "[\"" << json_escape(leaf) << "\"," << string_array_json(child_key) << "]";
        }
        out << "]}";
    }
    out << "],\"tree_direct_files\":[";
    first = true;
    for (auto row : state.direct_files) {
        auto files = row.second;
        std::sort(files.begin(), files.end());
        if (!first) out << ",";
        first = false;
        out << "{\"folder\":" << string_array_json(row.first) << ",\"indexes\":[";
        for (size_t i = 0; i < files.size(); ++i) {
            if (i) out << ",";
            out << files[i].second;
        }
        out << "]}";
    }
    out << "],\"tree_folder_entry_indexes\":[";
    first = true;
    for (const auto& [folder, indexes] : state.folder_entry_indexes) {
        if (!first) out << ",";
        first = false;
        out << "{\"folder\":" << string_array_json(folder) << ",\"indexes\":[";
        for (size_t i = 0; i < indexes.size(); ++i) {
            if (i) out << ",";
            out << indexes[i];
        }
        out << "]}";
    }
    out << "],\"tree_folder_preview_stats\":[";
    first = true;
    for (const auto& [folder, stats] : state.folder_stats) {
        if (!first) out << ",";
        first = false;
        out << "{\"folder\":" << string_array_json(folder) << ",\"stats\":["
            << std::get<0>(stats) << "," << std::get<1>(stats) << "," << std::get<2>(stats) << "]}";
    }
    out << "]";
    return out.str();
}

int run_scan_job(const fs::path& job_path, const fs::path& report_path) {
    try {
        const std::string job = read_text(job_path);
        const fs::path package_root = fs::path(find_string_value(job, "package_root"));
        std::vector<Entry> entries = scan_package_root(package_root);
        write_text(report_path, entries_json(entries));
        return 0;
    } catch (const std::exception& exc) {
        write_text(report_path, std::string("{\"status\":\"error\",\"backend\":\"") + kBackend + "\",\"message\":\"" + json_escape(exc.what()) + "\"}");
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int run_browser_state_job(const fs::path& job_path, const fs::path& report_path) {
    try {
        const std::string job = read_text(job_path);
        BrowserOptions options;
        options.filter_text = find_string_value(job, "filter_text");
        options.exclude_filter_text = find_string_value(job, "exclude_filter_text");
        options.extension_filter = find_string_value(job, "extension_filter");
        options.package_filter_text = find_string_value(job, "package_filter_text");
        options.structure_filter = find_string_value(job, "structure_filter");
        options.exclude_common_technical_suffixes = find_bool_value(job, "exclude_common_technical_suffixes", false);
        options.min_size_kb = static_cast<int>(find_int_value(job, "min_size_kb", 0));
        options.previewable_only = find_bool_value(job, "previewable_only", false);
        options.build_structure_children = find_bool_value(job, "build_structure_children", true);
        options.build_tree_index = find_bool_value(job, "build_tree_index", true);
        std::vector<Entry> entries = read_entries_tsv(fs::path(find_string_value(job, "entries_tsv")));
        std::vector<Entry> filtered;
        std::vector<int> filtered_indexes;
        filtered.reserve(entries.size());
        for (const Entry& entry : entries) {
            if (entry_matches(entry, options)) {
                filtered_indexes.push_back(entry.source_index);
                filtered.push_back(entry);
            }
        }
        int dds_count = 0;
        for (const Entry& entry : filtered) {
            if (extension_for(entry.path) == ".dds") ++dds_count;
        }
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"" << kBackend << "\",\"protocol\":" << kProtocol
            << ",\"filtered_indexes\":[";
        for (size_t i = 0; i < filtered_indexes.size(); ++i) {
            if (i) out << ",";
            out << filtered_indexes[i];
        }
        out << "],\"structure_children\":";
        out << (options.build_structure_children ? structure_children_json(entries) : "[]");
        out << ",";
        if (options.build_tree_index) {
            out << tree_json(build_tree(filtered));
        } else {
            out << "\"tree_child_folders\":[],\"tree_direct_files\":[],\"tree_folder_entry_indexes\":[],\"tree_folder_preview_stats\":[]";
        }
        out << ",\"tree_index_ready\":" << (options.build_tree_index ? "true" : "false") << ",\"dds_count\":" << dds_count << "}";
        write_text(report_path, out.str());
        return 0;
    } catch (const std::exception& exc) {
        write_text(report_path, std::string("{\"status\":\"error\",\"backend\":\"") + kBackend + "\",\"message\":\"" + json_escape(exc.what()) + "\"}");
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int run_derived_index_job(const fs::path& entries_path, const fs::path& report_path, const fs::path& progress_path) {
    try {
        std::vector<Entry> entries = read_entries_tsv(entries_path);
        write_progress_json(progress_path, "index", 0, static_cast<long long>(entries.size()));
        std::map<std::string, std::vector<int>> path_rows;
        std::map<std::string, std::vector<int>> basename_rows;
        std::map<std::string, std::vector<int>> extension_rows;
        for (size_t i = 0; i < entries.size(); ++i) {
            const Entry& entry = entries[i];
            const int index = static_cast<int>(i);
            const std::string normalized_path = lower_copy(slash_copy(entry.path));
            const std::string basename = lower_copy(basename_for(entry.path));
            const std::string ext = normalize_extension(extension_for(entry.path));
            if (!normalized_path.empty()) path_rows[normalized_path].push_back(index);
            if (!basename.empty()) basename_rows[basename].push_back(index);
            if (!ext.empty()) extension_rows[ext].push_back(index);
            if ((i + 1) % 100000 == 0) {
                write_progress_json(progress_path, "index", static_cast<long long>(i + 1), static_cast<long long>(entries.size()));
            }
        }
        for (auto& row : basename_rows) {
            std::vector<int>& rows = row.second;
            std::sort(rows.begin(), rows.end(), [&](int left, int right) {
                const std::string left_path = lower_copy(slash_copy(entries[static_cast<size_t>(left)].path));
                const std::string right_path = lower_copy(slash_copy(entries[static_cast<size_t>(right)].path));
                const int left_depth = slash_depth_for(left_path);
                const int right_depth = slash_depth_for(right_path);
                if (left_depth != right_depth) return left_depth > right_depth;
                if (left_path.size() != right_path.size()) return left_path.size() > right_path.size();
                return left_path < right_path;
            });
        }
        auto write_rows_json = [](std::ostream& out, const std::map<std::string, std::vector<int>>& rows_by_key) {
            out << "[";
            bool first_row = true;
            for (const auto& row : rows_by_key) {
                if (!first_row) out << ",";
                first_row = false;
                out << "[\"" << json_escape(row.first) << "\",[";
                for (size_t i = 0; i < row.second.size(); ++i) {
                    if (i) out << ",";
                    out << row.second[i];
                }
                out << "]]";
            }
            out << "]";
        };
        if (!report_path.parent_path().empty()) fs::create_directories(report_path.parent_path());
        std::ofstream out(report_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("could not write " + report_path.string());
        out << "{\"status\":\"ok\",\"backend\":\"" << kBackend << "\",\"protocol\":" << kProtocol
            << ",\"entry_count\":" << entries.size()
            << ",\"path_rows\":";
        write_rows_json(out, path_rows);
        out << ",\"basename_rows\":";
        write_rows_json(out, basename_rows);
        out << ",\"extension_rows\":";
        write_rows_json(out, extension_rows);
        out << "}";
        if (!out) throw std::runtime_error("could not finish writing " + report_path.string());
        write_progress_json(progress_path, "complete", static_cast<long long>(entries.size()), static_cast<long long>(entries.size()));
        return 0;
    } catch (const std::exception& exc) {
        write_text(report_path, std::string("{\"status\":\"error\",\"backend\":\"") + kBackend + "\",\"message\":\"" + json_escape(exc.what()) + "\"}");
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

struct NativeItemRecord {
    int item_id = 0;
    std::string internal_name;
    std::string display_name;
    std::vector<std::string> localized_names;
    std::vector<std::uint32_t> prefab_hashes;
    std::vector<std::string> model_stems;
    std::vector<std::string> pac_files;
    std::vector<std::string> icon_paths;
    std::vector<std::string> material_tags;
};

void add_unique(std::vector<std::string>& values, const std::string& value) {
    if (value.empty()) return;
    if (std::find(values.begin(), values.end(), value) == values.end()) values.push_back(value);
}

std::map<std::string, std::string> parse_localization_bin(const std::vector<char>& data) {
    std::map<std::string, std::string> rows;
    size_t pos = 0;
    while (pos + 8 < data.size()) {
        const std::uint32_t slen = read_u32(data, pos);
        if (slen > 0 && slen <= 50000 && pos + 4 + slen <= data.size()) {
            std::string id(data.begin() + static_cast<std::ptrdiff_t>(pos + 4), data.begin() + static_cast<std::ptrdiff_t>(pos + 4 + slen));
            bool digits = slen >= 6 && slen <= 20 && std::all_of(id.begin(), id.end(), [](unsigned char ch) { return std::isdigit(ch); });
            const size_t text_pos = pos + 4 + slen;
            if (digits && text_pos + 4 < data.size()) {
                const std::uint32_t text_len = read_u32(data, text_pos);
                if (text_len > 0 && text_len < 50000 && text_pos + 4 + text_len <= data.size()) {
                    std::string text(data.begin() + static_cast<std::ptrdiff_t>(text_pos + 4), data.begin() + static_cast<std::ptrdiff_t>(text_pos + 4 + text_len));
                    rows[id] = text;
                    pos = text_pos + 4 + text_len;
                    continue;
                }
            }
        }
        ++pos;
    }
    return rows;
}

std::string normalize_icon_model_stem(std::string value) {
    value = slash_copy(value);
    value = basename_for(value);
    value = lower_copy(value);
    const std::string ext = extension_for(value);
    if (ext == ".pac" || ext == ".prefab" || ext == ".pact") {
        value.resize(value.size() - ext.size());
    }
    return value;
}

std::map<std::uint32_t, std::string> parse_stringinfo_hashes(const std::vector<char>& data) {
    std::map<std::uint32_t, std::string> hashes;
    size_t pos = 0;
    while (pos + 8 < data.size()) {
        const std::uint32_t slen = read_u32(data, pos);
        if (slen >= 3 && slen <= 180 && pos + 4 + slen + 4 <= data.size()) {
            std::string text(data.begin() + static_cast<std::ptrdiff_t>(pos + 4), data.begin() + static_cast<std::ptrdiff_t>(pos + 4 + slen));
            while (!text.empty() && text.back() == '\0') text.pop_back();
            const std::string lower = lower_copy(text);
            const std::string prefix = "itemicon_prefab_";
            if (starts_with(lower, prefix)) {
                std::string model_stem = normalize_icon_model_stem(text.substr(prefix.size()));
                if (starts_with(model_stem, "cd_")) {
                    const std::uint32_t stored_hash = read_u32(data, pos + 4 + slen);
                    hashes[stored_hash] = model_stem;
                    hashes[hashlittle_bytes(text, 0xC5EDE)] = model_stem;
                    hashes[hashlittle_bytes(model_stem, 0xC5EDE)] = model_stem;
                }
            }
            pos += 4 + slen + 8;
            continue;
        }
        ++pos;
    }
    return hashes;
}

bool item_icon_model_reference_is_compatible(const std::string& internal_name, const std::string& model_stem) {
    const std::string a = lower_copy(internal_name);
    const std::string b = lower_copy(model_stem);
    static const std::vector<std::pair<std::string, std::string>> pairs = {
        {"onehandsword", "01_sword"}, {"twohandsword", "02_sword"}, {"twohandspear", "02_spear"},
        {"halberd", "02_alebard"}, {"alebard", "02_alebard"}, {"hammer", "02_hammer"},
        {"spear", "spear"}, {"shield", "03_shield"}, {"backpack", "bag"}, {"ring", "ring"},
        {"earring", "earring"}, {"necklace", "necklace"}, {"helm", "hel"}, {"helmet", "hel"},
        {"armor", "ub"}, {"cloak", "cloak"}, {"glove", "hand"}, {"boots", "foot"}, {"saddle", "horse_ub"}
    };
    for (const auto& pair : pairs) {
        if (a.find(pair.first) != std::string::npos && b.find(pair.second) != std::string::npos) return true;
    }
    return false;
}

std::vector<NativeItemRecord> parse_iteminfo_bin(
    const std::vector<char>& data,
    const std::map<std::string, std::map<std::string, std::string>>& loc_tables,
    const std::map<std::uint32_t, std::string>& icon_hashes
) {
    static const unsigned char marker[] = {0x00,0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x07,0x70,0x00,0x00,0x00};
    std::vector<NativeItemRecord> items;
    std::set<int> seen_ids;
    size_t idx = 0;
    while (idx + sizeof(marker) < data.size()) {
        auto it = std::search(data.begin() + static_cast<std::ptrdiff_t>(idx), data.end(), std::begin(marker), std::end(marker));
        if (it == data.end()) break;
        const size_t pos = static_cast<size_t>(std::distance(data.begin(), it));
        idx = pos + sizeof(marker);
        size_t name_start = pos;
        while (name_start > 0 && static_cast<unsigned char>(data[name_start - 1]) >= 0x21 && static_cast<unsigned char>(data[name_start - 1]) <= 0x7E) {
            --name_start;
            if (pos - name_start > 150) break;
        }
        if (pos - name_start < 3 || name_start < 8) continue;
        std::string name(data.begin() + static_cast<std::ptrdiff_t>(name_start), data.begin() + static_cast<std::ptrdiff_t>(pos));
        if (!std::isalpha(static_cast<unsigned char>(name[0]))) continue;
        if (!std::all_of(name.begin(), name.end(), [](unsigned char ch) { return std::isalnum(ch) || ch == '_'; })) continue;
        const std::uint32_t name_len = read_u32(data, name_start - 4);
        const std::uint32_t item_id = read_u32(data, name_start - 8);
        if (!(name_len == name.size() || name_len == name.size() + 1)) continue;
        if (item_id < 100 || item_id > 100000000 || seen_ids.count(static_cast<int>(item_id))) continue;
        seen_ids.insert(static_cast<int>(item_id));
        std::string loc_id;
        const size_t loc_off = pos + 18;
        if (loc_off + 4 < data.size()) {
            const std::uint32_t loc_len = read_u32(data, loc_off);
            if (loc_len > 5 && loc_len < 25 && loc_off + 4 + loc_len <= data.size()) {
                std::string candidate(data.begin() + static_cast<std::ptrdiff_t>(loc_off + 4), data.begin() + static_cast<std::ptrdiff_t>(loc_off + 4 + loc_len));
                if (std::all_of(candidate.begin(), candidate.end(), [](unsigned char ch) { return std::isdigit(ch); })) loc_id = candidate;
            }
        }
        NativeItemRecord record;
        record.item_id = static_cast<int>(item_id);
        record.internal_name = name;
        const size_t search_end = std::min(data.size(), pos + 800);
        for (size_t scan = pos + 14; scan + 15 < search_end; ++scan) {
            if (static_cast<unsigned char>(data[scan]) != 0x0E && static_cast<unsigned char>(data[scan]) != 0x0F) continue;
            const std::uint32_t count1 = read_u32(data, scan + 3);
            const std::uint32_t count2 = read_u32(data, scan + 7);
            if (!(count1 > 0 && count1 <= 5 && count2 > 0 && count2 <= 5)) continue;
            for (std::uint32_t hash_index = 0; hash_index < count2; ++hash_index) {
                const std::uint32_t value = read_u32(data, scan + 11 + hash_index * 4);
                if (value) record.prefab_hashes.push_back(value);
            }
            if (!record.prefab_hashes.empty()) break;
        }
        if (!icon_hashes.empty()) {
            const auto next_it = std::search(data.begin() + static_cast<std::ptrdiff_t>(idx), data.end(), std::begin(marker), std::end(marker));
            const size_t next_pos = next_it == data.end() ? pos + 2500 : static_cast<size_t>(std::distance(data.begin(), next_it));
            const size_t icon_end = std::min({data.size(), next_pos, pos + 2500});
            for (size_t scan = pos; scan + 4 <= icon_end; ++scan) {
                const std::uint32_t value = read_u32(data, scan);
                auto found = icon_hashes.find(value);
                if (found != icon_hashes.end() && item_icon_model_reference_is_compatible(name, found->second)) {
                    add_unique(record.model_stems, found->second);
                }
            }
        }
        std::set<std::string> seen_names;
        if (!loc_id.empty()) {
            for (const auto& table : loc_tables) {
                auto found = table.second.find(loc_id);
                if (found != table.second.end() && !found->second.empty()) {
                    const std::string key = lower_copy(found->second);
                    if (!seen_names.count(key)) {
                        record.localized_names.push_back(found->second);
                        seen_names.insert(key);
                    }
                }
            }
            auto eng_table = loc_tables.find("eng");
            if (eng_table != loc_tables.end()) {
                auto found = eng_table->second.find(loc_id);
                if (found != eng_table->second.end()) record.display_name = found->second;
            }
            if (record.display_name.empty() && !record.localized_names.empty()) record.display_name = record.localized_names.front();
        }
        items.push_back(std::move(record));
    }
    return items;
}

std::map<std::string, std::vector<std::string>> build_icon_path_index(const std::vector<Entry>& entries) {
    std::map<std::string, std::vector<std::string>> index;
    static const std::vector<std::string> prefixes = {"itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_"};
    for (const Entry& entry : entries) {
        const std::string lower_path = lower_copy(slash_copy(entry.path));
        if (extension_for(lower_path) != ".dds") continue;
        const std::string stem = stem_for_path(lower_path);
        if (lower_path.find("itemicon") == std::string::npos && std::none_of(prefixes.begin(), prefixes.end(), [&](const std::string& p) { return starts_with(stem, p); })) continue;
        std::string model_stem;
        for (const std::string& prefix : prefixes) {
            if (starts_with(stem, prefix)) {
                model_stem = normalize_icon_model_stem(stem.substr(prefix.size()));
                break;
            }
        }
        if (model_stem.empty()) {
            const size_t cd_pos = stem.find("cd_");
            if (cd_pos != std::string::npos) model_stem = normalize_icon_model_stem(stem.substr(cd_pos));
        }
        for (const std::string& key : model_candidate_bases(model_stem)) add_unique(index[key], slash_copy(entry.path));
    }
    return index;
}

std::string canonical_material_tag(std::string value) {
    value = lower_copy(value);
    std::string compact;
    for (unsigned char ch : value) if (std::isalnum(ch)) compact.push_back(static_cast<char>(ch));
    static const std::vector<std::pair<std::string, std::string>> aliases = {
        {"cloth", "cloth"}, {"cloths", "cloth"}, {"fabric", "cloth"}, {"leather", "leather"}, {"hide", "leather"},
        {"metal", "metal"}, {"iron", "metal"}, {"steel", "metal"}, {"wood", "wood"}, {"stone", "stone"},
        {"fur", "fur"}, {"hair", "hair"}, {"skin", "skin"}, {"bone", "bone"}, {"glass", "glass"},
        {"rope", "rope"}, {"crystal", "crystal"}, {"water", "water"}, {"dirt", "dirt"}, {"grass", "grass"}
    };
    for (const auto& alias : aliases) if (compact.find(alias.first) != std::string::npos) return alias.second;
    return {};
}

std::map<std::string, std::vector<std::string>> parse_material_index(const std::vector<char>& data) {
    std::map<std::string, std::vector<std::string>> index;
    std::vector<std::string> record_values;
    auto model_asset_path = [](std::string value) {
        value = slash_copy(value);
        const std::string lower = lower_copy(value);
        for (const std::string& suffix : {".pamlod", ".prefab", ".pac", ".pam"}) {
            const size_t pos = lower.find(suffix);
            if (pos != std::string::npos && lower.substr(0, pos + suffix.size()).find('/') != std::string::npos) {
                return value.substr(0, pos + suffix.size());
            }
        }
        return std::string();
    };
    auto flush = [&](const std::string& path) {
        const std::string normalized_path = model_asset_path(path);
        if (normalized_path.empty()) return;
        std::vector<std::string> tags;
        for (const std::string& value : record_values) add_unique(tags, canonical_material_tag(value));
        add_unique(tags, canonical_material_tag(normalized_path));
        if (tags.empty()) return;
        const std::string basename = lower_copy(basename_for(normalized_path));
        const std::string stem = stem_for_path(normalized_path);
        for (const std::string& key : {lower_copy(normalized_path), basename, stem}) {
            for (const std::string& tag : tags) add_unique(index[key], tag);
        }
    };
    size_t pos = 0;
    while (pos + 8 <= data.size()) {
        const std::uint32_t slen = read_u32(data, pos);
        if (slen >= 3 && slen <= 260 && pos + 4 + slen <= data.size()) {
            std::string text(data.begin() + static_cast<std::ptrdiff_t>(pos + 4), data.begin() + static_cast<std::ptrdiff_t>(pos + 4 + slen));
            while (!text.empty() && text.back() == '\0') text.pop_back();
            const std::string path = model_asset_path(text);
            if (!path.empty()) {
                flush(path);
                record_values.clear();
            } else if (!text.empty()) {
                record_values.push_back(text);
                if (record_values.size() > 48) record_values.erase(record_values.begin(), record_values.begin() + 16);
            }
            pos += 4 + slen;
            continue;
        }
        ++pos;
    }
    return index;
}

std::map<std::uint32_t, std::string> build_model_hash_table(const std::vector<Entry>& entries) {
    std::map<std::uint32_t, std::string> table;
    static const std::vector<std::string> suffixes = {
        "", "_l", "_r", "_u", "_s", "_t", "_c", "_d", "_index01", "_index02", "_index03",
        "_index01_l", "_index01_r", "_index02_l", "_index02_r", "_index03_l", "_index03_r", "_sub01", "_sub02", "_sub03"
    };
    for (const Entry& entry : entries) {
        const std::string lower_path = lower_copy(slash_copy(entry.path));
        const std::string ext = extension_for(lower_path);
        if (package_group_for(entry) != "0009" || !(ext == ".prefab" || ext == ".pac" || ext == ".pact")) continue;
        const std::string base = stem_for_path(lower_path);
        for (const std::string& candidate_base : model_candidate_bases(base)) {
            for (const std::string& suffix : suffixes) {
                const std::string name = candidate_base + suffix;
                table.emplace(hashlittle_bytes(name, 0xC5EDE), name);
            }
        }
    }
    return table;
}

std::string json_string_array(const std::vector<std::string>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(values[i]) << "\"";
    }
    out << "]";
    return out.str();
}

std::string json_u32_array(const std::vector<std::uint32_t>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) out << ",";
        out << values[i];
    }
    out << "]";
    return out.str();
}

void append_map_json(std::ostringstream& out, const std::map<std::string, std::string>& rows) {
    out << "[";
    bool first = true;
    for (const auto& row : rows) {
        if (!first) out << ",";
        first = false;
        out << "[\"" << json_escape(row.first) << "\",\"" << json_escape(row.second) << "\"]";
    }
    out << "]";
}

int run_item_index_job(const fs::path& entries_path, const fs::path& work_dir, const fs::path& report_path) {
    try {
        std::vector<Entry> entries = read_entries_tsv(entries_path);
        std::map<std::string, std::map<std::string, std::string>> loc_tables;
        for (const std::string& lang : {"kor","eng","jpn","rus","tur","spa-es","spa-mx","fre","ger","ita","pol","por-br","zho-tw","zho-cn"}) {
            std::vector<char> data = read_binary_if_exists(work_dir / ("loc_" + lang + ".bin"));
            if (!data.empty()) loc_tables[lang] = parse_localization_bin(data);
        }
        const auto icon_hashes = parse_stringinfo_hashes(read_binary_if_exists(work_dir / "stringinfo.bin"));
        auto items = parse_iteminfo_bin(read_binary_if_exists(work_dir / "iteminfo.bin"), loc_tables, icon_hashes);
        const auto icon_index = build_icon_path_index(entries);
        const auto material_index = parse_material_index(read_binary_if_exists(work_dir / "partprefabdyeslotinfo.bin"));
        const auto hash_table = build_model_hash_table(entries);
        std::map<std::string, std::string> aliases;
        std::map<std::string, std::string> display_names;
        std::map<std::string, std::string> exact_display_names;
        std::map<std::string, std::string> related_display_names;

        auto add_display = [](std::map<std::string, std::string>& rows, const std::string& key, const std::string& value) {
            if (key.empty() || value.empty()) return;
            auto found = rows.find(key);
            if (found == rows.end()) rows[key] = value;
            else if (found->second.find(value) == std::string::npos) found->second += " / " + value;
        };
        auto add_alias = [](std::map<std::string, std::string>& rows, const std::string& key, const std::string& value) {
            if (key.empty() || value.empty()) return;
            auto found = rows.find(key);
            if (found == rows.end()) rows[key] = value;
            else found->second += " " + value;
        };

        std::vector<NativeItemRecord> linked_items;
        for (NativeItemRecord& item : items) {
            std::vector<std::string> exact_models;
            std::vector<std::string> related_models = item.model_stems;
            for (std::uint32_t hash : item.prefab_hashes) {
                auto found = hash_table.find(hash);
                if (found != hash_table.end()) add_unique(exact_models, found->second);
            }
            for (const std::string& resolved : exact_models) {
                for (const std::string& key : model_candidate_bases(resolved)) {
                    auto icons = icon_index.find(key);
                    if (icons != icon_index.end()) for (const std::string& icon : icons->second) add_unique(item.icon_paths, icon);
                }
            }
            for (const std::string& resolved : related_models) {
                for (const std::string& key : model_candidate_bases(resolved)) {
                    auto icons = icon_index.find(key);
                    if (icons != icon_index.end()) for (const std::string& icon : icons->second) add_unique(item.icon_paths, icon);
                }
            }
            for (const auto& pair : {std::make_pair(exact_models, std::string("exact")), std::make_pair(related_models, std::string("related"))}) {
                for (const std::string& resolved : pair.first) {
                    const std::string base = strip_model_variant_suffix(resolved);
                    if (base.empty()) continue;
                    const std::string pac_name = base + ".pac";
                    add_unique(item.pac_files, pac_name);
                    std::string terms = lower_copy(item.display_name + " " + item.internal_name + " " + base + " " + pac_name + " " + resolved);
                    for (const std::string& name : item.localized_names) terms += " " + lower_copy(name);
                    add_alias(aliases, base, terms);
                    if (!item.display_name.empty()) {
                        add_display(display_names, base, item.display_name);
                        if (pair.second == "exact") add_display(exact_display_names, normalize_icon_model_stem(resolved), item.display_name);
                        else add_display(related_display_names, base, item.display_name);
                    }
                }
            }
            for (const std::string& model : item.pac_files) {
                for (const std::string& key : model_candidate_bases(stem_for_path(model))) {
                    auto found = material_index.find(key);
                    if (found != material_index.end()) for (const std::string& tag : found->second) add_unique(item.material_tags, tag);
                }
            }
            if (!item.material_tags.empty()) {
                std::string material_terms;
                for (const std::string& tag : item.material_tags) material_terms += " " + tag;
                for (const std::string& model : item.pac_files) add_alias(aliases, strip_model_variant_suffix(stem_for_path(model)), material_terms);
            }
            if (!item.pac_files.empty() || !item.model_stems.empty()) linked_items.push_back(std::move(item));
        }

        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"" << kBackend << "\",\"protocol\":" << kProtocol
            << ",\"items\":[";
        for (size_t i = 0; i < linked_items.size(); ++i) {
            const auto& item = linked_items[i];
            if (i) out << ",";
            out << "{\"item_id\":" << item.item_id
                << ",\"internal_name\":\"" << json_escape(item.internal_name)
                << "\",\"display_name\":\"" << json_escape(item.display_name)
                << "\",\"localized_names\":" << json_string_array(item.localized_names)
                << ",\"prefab_hashes\":" << json_u32_array(item.prefab_hashes)
                << ",\"model_stems\":" << json_string_array(item.model_stems)
                << ",\"pac_files\":" << json_string_array(item.pac_files)
                << ",\"icon_paths\":" << json_string_array(item.icon_paths)
                << ",\"material_tags\":" << json_string_array(item.material_tags)
                << "}";
        }
        out << "],\"model_base_aliases\":";
        append_map_json(out, aliases);
        out << ",\"model_base_display_names\":";
        append_map_json(out, display_names);
        out << ",\"model_base_exact_display_names\":";
        append_map_json(out, exact_display_names);
        out << ",\"model_base_related_display_names\":";
        append_map_json(out, related_display_names);
        out << ",\"item_count\":" << linked_items.size()
            << ",\"model_hash_count\":" << hash_table.size()
            << ",\"icon_path_key_count\":" << icon_index.size()
            << ",\"material_key_count\":" << material_index.size()
            << "}";
        write_text(report_path, out.str());
        return 0;
    } catch (const std::exception& exc) {
        write_text(report_path, std::string("{\"status\":\"error\",\"backend\":\"") + kBackend + "\",\"message\":\"" + json_escape(exc.what()) + "\"}");
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int run_entry_read_job(const fs::path& job_path, const fs::path& output_path, const fs::path& report_path) {
    try {
        const std::string job = read_text(job_path);
        const fs::path paz_file = fs::path(find_string_value(job, "paz_file"));
        const std::string virtual_path = find_string_value(job, "path");
        const std::uint64_t offset = static_cast<std::uint64_t>(find_int_value(job, "offset", 0));
        const std::uint64_t comp_size = static_cast<std::uint64_t>(find_int_value(job, "comp_size", 0));
        const std::uint64_t orig_size = static_cast<std::uint64_t>(find_int_value(job, "orig_size", 0));
        const std::uint32_t flags = static_cast<std::uint32_t>(find_int_value(job, "flags", 0));
        const bool compressed = comp_size != orig_size;
        const bool encrypted = (flags >> 4u) != 0u;
        if (compressed || encrypted) {
            std::ostringstream out;
            out << "{\"status\":\"unsupported\",\"supported\":false,\"backend\":\"" << kBackend << "\",\"protocol\":" << kProtocol
                << ",\"path\":\"" << json_escape(virtual_path) << "\",\"fallback_reason\":\"";
            if (encrypted) out << "encrypted archive entries stay on Python fallback";
            else out << "compressed archive entries stay on Python fallback";
            out << "\",\"compression_type\":" << (flags & 0x0Fu) << ",\"encrypted\":" << (encrypted ? "true" : "false") << "}";
            write_text(report_path, out.str());
            return 0;
        }
        if (orig_size == 0) throw std::runtime_error("entry has zero original size");
        std::ifstream in(paz_file, std::ios::binary);
        if (!in) throw std::runtime_error("could not open PAZ " + paz_file.string());
        in.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
        std::vector<char> data(static_cast<size_t>(orig_size));
        in.read(data.data(), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(in.gcount()) != data.size()) throw std::runtime_error("PAZ entry payload is truncated");
        if (!output_path.parent_path().empty()) fs::create_directories(output_path.parent_path());
        std::ofstream out_file(output_path, std::ios::binary | std::ios::trunc);
        if (!out_file) throw std::runtime_error("could not write entry output");
        out_file.write(data.data(), static_cast<std::streamsize>(data.size()));
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"supported\":true,\"backend\":\"" << kBackend << "\",\"protocol\":" << kProtocol
            << ",\"path\":\"" << json_escape(virtual_path) << "\",\"output_path\":\"" << json_escape(output_path.string())
            << "\",\"bytes_written\":" << data.size() << ",\"decompressed\":false,\"note\":\"NativeRaw\"}";
        write_text(report_path, out.str());
        return 0;
    } catch (const std::exception& exc) {
        write_text(report_path, std::string("{\"status\":\"error\",\"supported\":false,\"backend\":\"") + kBackend + "\",\"message\":\"" + json_escape(exc.what()) + "\",\"fallback_reason\":\"native entry read failed\"}");
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc >= 2 && std::string(argv[1]) == "--version") {
            std::cout << "cdmw-archive-accelerator protocol=" << kProtocol << "\n";
            return 0;
        }
        if (argc >= 4 && std::string(argv[1]) == "scan-job") {
            return run_scan_job(fs::path(argv[2]), fs::path(argv[3]));
        }
        if (argc >= 4 && std::string(argv[1]) == "browser-state-job") {
            return run_browser_state_job(fs::path(argv[2]), fs::path(argv[3]));
        }
        if (argc >= 4 && std::string(argv[1]) == "derived-index-job") {
            fs::path progress_path;
            if (argc >= 5) progress_path = fs::path(argv[4]);
            return run_derived_index_job(fs::path(argv[2]), fs::path(argv[3]), progress_path);
        }
        if (argc >= 5 && std::string(argv[1]) == "item-index-job") {
            return run_item_index_job(fs::path(argv[2]), fs::path(argv[3]), fs::path(argv[4]));
        }
        if (argc >= 5 && std::string(argv[1]) == "entry-read-job") {
            return run_entry_read_job(fs::path(argv[2]), fs::path(argv[3]), fs::path(argv[4]));
        }
        std::cerr << "usage: cdmw-archive-accelerator --version | scan-job <job.json> <report.json> [progress.json] | browser-state-job <job.json> <report.json> [progress.json] | derived-index-job <entries.tsv> <report.json> [progress.json] | item-index-job <entries.tsv> <work-dir> <report.json> | entry-read-job <job.json> <output.bin> <report.json>\n";
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
