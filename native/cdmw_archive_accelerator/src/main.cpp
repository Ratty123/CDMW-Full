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
    for (const auto& item : fs::recursive_directory_iterator(package_root)) {
        if (item.is_regular_file() && lower_copy(item.path().extension().string()) == ".pamt") pamt_files.push_back(item.path());
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
        if (argc >= 5 && std::string(argv[1]) == "entry-read-job") {
            return run_entry_read_job(fs::path(argv[2]), fs::path(argv[3]), fs::path(argv[4]));
        }
        std::cerr << "usage: cdmw-archive-accelerator --version | scan-job <job.json> <report.json> [progress.json] | browser-state-job <job.json> <report.json> [progress.json] | entry-read-job <job.json> <output.bin> <report.json>\n";
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 2;
    }
}
