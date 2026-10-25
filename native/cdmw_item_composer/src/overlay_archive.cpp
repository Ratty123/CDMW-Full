// archive_overlay.build_overlay_archive: a whole archive directory (0.pamt + 0.paz) built
// from scratch, holding only the files a composition changed.
#include "composer_internal.hpp"

namespace cdmw::compose {
using namespace detail;
namespace {

constexpr std::size_t paz_alignment = 16;
constexpr std::uint32_t pamt_constant = 0x610E0232;
constexpr std::uint32_t folder_hash_seed = 0xC5EDE;
constexpr std::uint32_t no_parent = 0xFFFFFFFF;

// str.isspace(): general category Zs, or bidirectional class WS, B or S.
bool python_space(std::uint32_t c) {
    return c == ' ' || (c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x1F) || c == 0x85 || c == 0xA0 || c == 0x1680 ||
           (c >= 0x2000 && c <= 0x200A) || c == 0x2028 || c == 0x2029 || c == 0x202F || c == 0x205F || c == 0x3000;
}
bool slash(std::uint32_t c) { return c == '/'; }

// One code point of valid UTF-8 starting at `at`, and its length.
std::pair<std::uint32_t, std::size_t> code_point(const std::string& text, std::size_t at) {
    const auto lead = static_cast<unsigned char>(text[at]);
    const std::size_t length = lead < 0x80 ? 1 : lead < 0xE0 ? 2 : lead < 0xF0 ? 3 : 4;
    std::uint32_t value = length == 1 ? lead : lead & (0x7Fu >> length);
    for (std::size_t i = 1; i < length; ++i) value = (value << 6) | (static_cast<unsigned char>(text[at + i]) & 0x3Fu);
    return {value, length};
}

// str.strip(chars) over code points.
std::string strip(const std::string& text, bool (*drop)(std::uint32_t)) {
    std::size_t begin = 0, end = text.size();
    while (begin < end) {
        const auto [value, length] = code_point(text, begin);
        if (!drop(value)) break;
        begin += length;
    }
    while (end > begin) {
        auto start = end - 1;
        while (start > begin && (static_cast<unsigned char>(text[start]) & 0xC0) == 0x80) --start;
        if (!drop(code_point(text, start).first)) break;
        end = start;
    }
    return text.substr(begin, end - begin);
}

// _normalize: str(path).replace("\\", "/").strip().strip("/").strip()
std::string normalize(const std::string& path) {
    if (!valid_utf8(reinterpret_cast<const std::uint8_t*>(path.data()), path.size())) throw Unsupported("overlay paths must be UTF-8");
    return strip(strip(strip(replace_all(path, "\\", "/"), python_space), slash), python_space);
}

std::pair<std::string, std::string> split(const std::string& path) {
    const auto slash = path.rfind('/');
    if (slash == std::string::npos) return {"", path};
    return {path.substr(0, slash), path.substr(slash + 1)};
}

// _trie_block: each string hangs off the longest string already written that prefixes it.
std::pair<Bytes, std::map<std::string, std::uint32_t>> trie_block(const std::vector<std::string>& strings) {
    Bytes block;
    std::map<std::string, std::uint32_t> offsets;
    std::vector<const std::string*> written;  // insertion order, as Python's dict iterates
    for (const auto& text : strings) {
        if (offsets.count(text)) continue;
        const std::string* prefix = nullptr;
        for (const auto* candidate : written)
            if (candidate->size() > (prefix ? prefix->size() : 0) && text.compare(0, candidate->size(), *candidate) == 0) prefix = candidate;
        const auto parent = prefix ? offsets.at(*prefix) : no_parent;
        const auto rest = text.substr(prefix ? prefix->size() : 0);
        if (rest.size() > 255) throw FormatError("'" + text + "' is longer than a name record can hold (255 bytes)");
        const auto at = static_cast<std::uint32_t>(block.size());
        put_u32(block, parent);
        block.push_back(static_cast<std::uint8_t>(rest.size()));
        block.insert(block.end(), rest.begin(), rest.end());
        written.push_back(&offsets.emplace(text, at).first->first);
    }
    return {std::move(block), std::move(offsets)};
}

std::uint32_t fits(std::uint64_t value) {
    if (value > 0xFFFFFFFFull) throw FormatError("'I' format requires 0 <= number <= 4294967295");
    return static_cast<std::uint32_t>(value);
}

}  // namespace

OverlayArchive build_overlay_archive(const std::vector<OverlayFile>& files) {
    if (files.empty()) throw FormatError("an overlay needs at least one file");
    std::map<std::string, std::vector<OverlayFile>> by_folder;
    for (const auto& item : files) {
        const auto clean = normalize(item.path);
        if (clean.empty()) throw FormatError("an overlay file needs a path");
        const auto [folder, name] = split(clean);
        if (name.empty()) throw FormatError("'" + item.path + "' names no file");
        by_folder[folder].push_back({clean, item.payload, item.orig_size, item.flags});
    }
    // Every folder on the way down to a file, not only the folder holding it.
    std::set<std::string> every_folder;
    for (const auto& [folder, _items] : by_folder) {
        every_folder.insert(folder);
        for (auto slash = folder.find('/'); slash != std::string::npos; slash = folder.find('/', slash + 1))
            every_folder.insert(folder.substr(0, slash));
    }
    if (!by_folder.count("")) every_folder.erase("");

    struct FileRecord {
        std::string name;
        std::uint64_t offset, stored, orig, flags;
    };
    struct FolderRecord {
        std::uint32_t hash;
        std::string folder;
        std::size_t start, count;
    };
    OverlayArchive archive;
    std::vector<FileRecord> file_records;
    std::vector<FolderRecord> folder_records;
    for (const auto& folder : every_folder) {  // byte order is Python's code point order
        std::vector<const OverlayFile*> items;
        if (const auto found = by_folder.find(folder); found != by_folder.end())
            for (const auto& item : found->second) items.push_back(&item);
        std::stable_sort(items.begin(), items.end(), [](const OverlayFile* x, const OverlayFile* y) { return split(x->path).second < split(y->path).second; });
        const auto start = file_records.size();
        for (const auto* item : items) {
            if (archive.paz.size() % paz_alignment) archive.paz.resize(archive.paz.size() + paz_alignment - archive.paz.size() % paz_alignment);
            const auto offset = archive.paz.size();
            append(archive.paz, item->payload);
            file_records.push_back({split(item->path).second, offset, item->payload.size(), item->orig_size, item->flags});
            archive.entries.push_back({item->path, offset, item->payload.size(), item->orig_size});
        }
        folder_records.push_back({hashlittle(reinterpret_cast<const std::uint8_t*>(folder.data()), folder.size(), folder_hash_seed),
                                  folder, start, file_records.size() - start});
    }
    // Every shipped .paz is a whole number of sixteen-byte blocks.
    if (archive.paz.size() % paz_alignment) archive.paz.resize(archive.paz.size() + paz_alignment - archive.paz.size() % paz_alignment);

    std::vector<std::string> folders, names;
    for (const auto& record : folder_records)
        if (!record.folder.empty()) folders.push_back(record.folder);
    for (const auto& record : file_records) names.push_back(record.name);
    const auto [dir_block, dir_offsets] = trie_block(folders);
    const auto [name_block, name_offsets] = trie_block(names);

    Bytes& out = archive.pamt;
    put_u32(out, 0);
    put_u32(out, 1);
    put_u32(out, pamt_constant);
    put_u32(out, 0);
    put_u32(out, pa_checksum(archive.paz.data(), archive.paz.size()));
    put_u32(out, fits(archive.paz.size()));
    put_u32(out, static_cast<std::uint32_t>(dir_block.size()));
    append(out, dir_block);
    put_u32(out, static_cast<std::uint32_t>(name_block.size()));
    append(out, name_block);
    put_u32(out, static_cast<std::uint32_t>(folder_records.size()));
    for (const auto& record : folder_records) {
        put_u32(out, record.hash);
        put_u32(out, record.folder.empty() ? no_parent : dir_offsets.at(record.folder));
        put_u32(out, static_cast<std::uint32_t>(record.start));
        put_u32(out, static_cast<std::uint32_t>(record.count));
    }
    put_u32(out, static_cast<std::uint32_t>(file_records.size()));
    for (const auto& record : file_records) {
        put_u32(out, name_offsets.at(record.name));
        put_u32(out, fits(record.offset));
        put_u32(out, fits(record.stored));
        put_u32(out, fits(record.orig));
        put_u16(out, 0);
        if (record.flags > 0xFFFF) throw FormatError("ushort format requires 0 <= number <= 65535");
        put_u16(out, static_cast<std::uint16_t>(record.flags));
    }
    archive.pamt_checksum = pa_checksum(out.data() + 12, out.size() - 12);
    for (std::size_t i = 0; i < 4; ++i) out[i] = static_cast<std::uint8_t>(archive.pamt_checksum >> (8 * i));
    return archive;
}

}  // namespace cdmw::compose
