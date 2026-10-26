// overlay_merge.merge_overlay_files: three-way composition with record-level conflicts.
//
// The game replaces whole files. Independent installs instead own rows, shop entries,
// group memberships and registry records; their containers are rebuilt after merging.
#include "composer_internal.hpp"

#include <unordered_set>

namespace cdmw::compose {
using namespace detail;
namespace {

bool same(const Blob& x, const Blob& y) { return x == y || (x && y && *x == *y); }
Blob blob(Bytes data) { return std::make_shared<const Bytes>(std::move(data)); }

Blob merge_blob(const Blob& before, const Blob& after, const Blob& current, const std::string& where) {
    if (same(before, after) || same(current, after)) return current;
    if (same(current, before)) return after;
    same_record(where);
}

// path.rsplit('/', 1)[-1].split('.')[0]
std::string table_name(const std::string& path) {
    const auto slash = path.rfind('/');
    const auto file = slash == std::string::npos ? path : path.substr(slash + 1);
    return file.substr(0, file.find('.'));
}

std::string lower_ascii(std::string text) {
    for (auto& c : text) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return text;
}

// _store: shop entries pair by order index. Independently exported installs both append at
// the next order, so an added entry finds its place by item identity instead.
Bytes merge_store(const Bytes& raw_before, const Bytes& raw_after, const Bytes& raw_current, const std::string& where, bool current_layout) {
    const auto b = parse_store_row(raw_before, current_layout);
    const auto a = parse_store_row(raw_after, current_layout);
    const auto c = parse_store_row(raw_current, current_layout);
    const auto normalized = [](const StoreRow& row) {
        auto entries = row.entries;
        for (auto& entry : entries) {
            entry.stock_index = 0;
            entry.offset = entry.end = -1;
        }
        return entries;
    };
    const auto original = normalized(b), incoming = normalized(a), present = normalized(c);
    std::set<std::uint64_t> base_orders, occupied;
    for (const auto& entry : original) base_orders.insert(entry.order_index);
    for (const auto* rows : {&incoming, &present})
        for (const auto& entry : *rows) occupied.insert(entry.order_index);
    std::vector<const StockEntry*> current_new;
    for (const auto& entry : present)
        if (!base_orders.count(entry.order_index)) current_new.push_back(&entry);
    std::vector<StockEntry> adjusted;
    for (auto entry : incoming) {
        if (!base_orders.count(entry.order_index)) {
            std::vector<const StockEntry*> matches;
            for (const auto* candidate : current_new)
                if (candidate->item_key == entry.item_key) matches.push_back(candidate);
            if (matches.size() > 1)
                throw OverlayConflict("Ambiguous added shop entries in " + where + " for item " + std::to_string(entry.item_key) + ".");
            if (!matches.empty()) {
                entry.order_index = matches.front()->order_index;
            } else if (std::any_of(current_new.begin(), current_new.end(), [&](const StockEntry* x) { return x->order_index == entry.order_index; })) {
                const auto order = occupied.empty() ? 0 : *occupied.rbegin() + 1;
                occupied.insert(order);
                entry.order_index = order;
            }
        }
        adjusted.push_back(std::move(entry));
    }
    auto entries = merge_records(original, adjusted, present, [](const StockEntry& entry) { return entry.order_index; }, where);
    // Buyable entries precede the sell-only entries in the shipped grammar.
    std::stable_partition(entries.begin(), entries.end(), [](const StockEntry& entry) { return entry.is_buyable(); });
    for (std::size_t index = 0; index < entries.size(); ++index) entries[index].stock_index = index;
    StoreRow row = c;
    row.prefix = merge_value(b.prefix, a.prefix, c.prefix, where);
    row.tail = merge_value(b.tail, a.tail, c.tail, where);
    row.store_type = merge_value(b.store_type, a.store_type, c.store_type, where);
    row.buyable_count = static_cast<std::uint64_t>(std::count_if(entries.begin(), entries.end(), [](const StockEntry& e) { return e.is_buyable(); }));
    row.sellable_count = static_cast<std::uint64_t>(std::count_if(entries.begin(), entries.end(), [](const StockEntry& e) { return e.is_sellable(); }));
    row.entries = std::move(entries);
    return encode_store_row(row);
}

// _group: memberships merge as records.
Bytes merge_group(const Bytes& raw_before, const Bytes& raw_after, const Bytes& raw_current, const std::string& where) {
    const auto b = parse_item_group_row(raw_before), a = parse_item_group_row(raw_after), c = parse_item_group_row(raw_current);
    auto members = merge_records(b.members, a.members, c.members, [](std::uint32_t member) { return std::uint64_t(member); }, where);
    ItemGroupRow row = c;
    row.members = std::move(members);
    row.prefix = merge_value(b.prefix, a.prefix, c.prefix, where);
    row.tail = merge_value(b.tail, a.tail, c.tail, where);
    row.subgroups = merge_value(b.subgroups, a.subgroups, c.subgroups, where);
    return encode_item_group_row(row);
}

std::optional<Bytes> merge_row(const Bytes* before, const Bytes* after, const Bytes* current, const std::string& where, const std::string& path) {
    try {
        return merge_optional(before, after, current, where);
    } catch (const OverlayConflict&) {
        if (!before || !after || !current) throw;
        const auto name = table_name(path);
        if (name == "storeinfo") return merge_store(*before, *after, *current, where, ends_with(path, ".staticinfobody"));
        if (name == "itemgroupinfo") return merge_group(*before, *after, *current, where);
        throw;
    }
}

using Record = std::pair<Bytes, Bytes>;  // primary key, row bytes
struct Table {
    PabghTable directory;
    std::vector<Record> records;  // payload order
};

// _table
Table read_table(const Bytes& body, const Bytes& header) {
    Table table{parse_pabgh_table(header, &body), {}};
    const auto& directory = table.directory;
    if (header.size() != directory.header_size + directory.rows.size() * (directory.key_width + 4))
        throw OverlayConflict("Unsupported table directory layout.");
    const auto spans = row_spans(directory, body.size());
    if (spans.size() != directory.rows.size() || (!spans.empty() && spans.front().start != 0))
        throw OverlayConflict("Incomplete table row directory.");
    std::unordered_set<Bytes, KeyHash> keys;
    keys.reserve(spans.size());
    table.records.reserve(spans.size());
    for (const auto& span : spans) {
        table.records.emplace_back(span.row->key, slice(body, span.start, span.end));
        keys.insert(span.row->key);
    }
    if (keys.size() != table.records.size()) throw OverlayConflict("Duplicate primary keys in an overlay table.");
    return table;
}

// _table_pair: rows merge by primary key; the payload follows the merged order and the
// directory keeps its own order, current's first.
std::pair<Bytes, Bytes> merge_table_pair(const FileMap& before, const FileMap& after, const FileMap& current,
                                         const std::string& path, const std::string& head) {
    const auto b = read_table(*before.get(path), *before.get(head));
    const auto a = read_table(*after.get(path), *after.get(head));
    const auto c = read_table(*current.get(path), *current.get(head));
    const auto layout = [](const Table& t) { return std::make_pair(t.directory.key_width, t.directory.header_size); };
    if (layout(b) != layout(a) || layout(a) != layout(c)) throw OverlayConflict("Table layout changed in " + path + ".");
    const auto rows = merge_records(b.records, a.records, c.records, [](const Record& r) { return r.first; }, path,
        [&](const Record* old, const Record* incoming, const Record* present, const std::string&) -> std::optional<Record> {
            const auto& key = (incoming ? incoming : present ? present : old)->first;
            auto raw = merge_row(old ? &old->second : nullptr, incoming ? &incoming->second : nullptr,
                                 present ? &present->second : nullptr, path + " [record " + decimal_le(key) + "]", path);
            if (!raw) return std::nullopt;
            return Record{key, std::move(*raw)};
        });
    std::unordered_map<Bytes, std::uint64_t, KeyHash> offsets;
    offsets.reserve(rows.size());
    Bytes payload;
    for (const auto& [key, raw] : rows) {
        offsets[key] = payload.size();
        append(payload, raw);
    }
    std::vector<const Bytes*> ordered;
    std::unordered_set<Bytes, KeyHash> seen;
    for (const auto* table : {&c, &a})
        for (const auto& row : table->directory.rows)
            if (seen.insert(row.key).second && offsets.count(row.key)) ordered.push_back(&row.key);
    const auto count_width = c.directory.header_size;
    if (count_width < 8 && (std::uint64_t(rows.size()) >> (8 * count_width)) != 0) throw FormatError("int too big to convert");
    Bytes header;
    put_le(header, rows.size(), count_width);
    for (const auto* key : ordered) {
        const auto offset = offsets.at(*key);
        if (offset > 0xFFFFFFFFull) throw FormatError("'I' format requires 0 <= number <= 4294967295");
        append(header, *key);
        put_u32(header, static_cast<std::uint32_t>(offset));
    }
    read_table(payload, header);
    return {std::move(payload), std::move(header)};
}

Bytes merge_paloc(const Bytes& raw_before, const Bytes& raw_after, const Bytes& raw_current, const std::string& where) {
    const auto b = parse_paloc(raw_before), a = parse_paloc(raw_after), c = parse_paloc(raw_current);
    const auto entries = merge_records(b.entries, a.entries, c.entries, [](const LocalizationEntry& e) { return e.key; }, where);
    std::set<Bytes> existing;
    for (const auto& entry : c.entries) existing.insert(entry.key);
    LocalizationTable kept;
    kept.source_container = c.source_container;
    std::vector<LocalizationEntry> additions;
    for (const auto& entry : entries) (existing.count(entry.key) ? kept.entries : additions).push_back(entry);
    return encode_paloc(add_localization_entries(std::move(kept), additions));
}

Bytes merge_pappt(const Bytes& raw_before, const Bytes& raw_after, const Bytes& raw_current, const std::string& where) {
    const auto b = parse_pappt(raw_before), a = parse_pappt(raw_after), c = parse_pappt(raw_current);
    auto table = c;
    table.records = merge_records(b.records, a.records, c.records, [](const PartPrefabRecord& r) { return r.stem; }, where);
    table.head_records = merge_records(b.head_records, a.head_records, c.head_records, [](const HeadPrefabRecord& r) { return r.stem; }, where);
    table.reserved = merge_value(b.reserved, a.reserved, c.reserved, where);
    table.tag_prefix = merge_value(b.tag_prefix, a.tag_prefix, c.tag_prefix, where);
    return encode_pappt(table);
}

struct TextureRecord {
    std::uint32_t checksum{};
    std::optional<Bytes> header;  // None for collision rows
    std::uint8_t collision_start{}, collision_end{};
    Bytes block_infos;
    bool operator==(const TextureRecord&) const = default;
};

std::vector<TextureRecord> texture_records(const PathcTable& table) {
    std::vector<TextureRecord> records;
    for (const auto& entry : table.entries) {
        TextureRecord record{entry.checksum, std::nullopt, entry.collision_start, entry.collision_end, entry.block_infos};
        if (entry.is_direct()) {
            if (entry.header_index >= table.headers.size()) throw FormatError("tuple index out of range");
            record.header = table.headers[static_cast<std::size_t>(entry.header_index)];
        }
        records.push_back(std::move(record));
    }
    return records;
}

Bytes merge_pathc(const Bytes& raw_before, const Bytes& raw_after, const Bytes& raw_current, const std::string& where) {
    const auto b = parse_pathc(raw_before), a = parse_pathc(raw_after), c = parse_pathc(raw_current);
    const auto rb = texture_records(b), ra = texture_records(a), rc = texture_records(c);
    auto merged = merge_records(rb, ra, rc, [](const TextureRecord& r) { return std::uint64_t(r.checksum); }, where);
    // sorted() on (checksum, header-or-None, ...) tuples: unique checksums sort by checksum
    // alone; a repeated one would compare None with bytes, which Python may refuse.
    std::stable_sort(merged.begin(), merged.end(), [](const TextureRecord& x, const TextureRecord& y) { return x.checksum < y.checksum; });
    for (std::size_t i = 1; i < merged.size(); ++i)
        if (merged[i].checksum == merged[i - 1].checksum) throw Unsupported("repeated texture checksums");
    auto table = c;
    std::map<Bytes, std::size_t> first;
    for (std::size_t i = 0; i < table.headers.size(); ++i) first.emplace(table.headers[i], i);
    table.entries.clear();
    for (const auto& record : merged) {
        PathcEntry entry{record.checksum, 0xFFFF, record.collision_start, record.collision_end, record.block_infos};
        if (record.header) {
            auto found = first.find(*record.header);
            if (found == first.end()) {
                found = first.emplace(*record.header, table.headers.size()).first;
                table.headers.push_back(*record.header);
            }
            entry.header_index = found->second;
        }
        table.entries.push_back(std::move(entry));
    }
    table.reserved = merge_value(b.reserved, a.reserved, c.reserved, where);
    table.header_size = merge_value(b.header_size, a.header_size, c.header_size, where);
    table.collisions = merge_value(b.collisions, a.collisions, c.collisions, where);
    table.filenames = merge_value(b.filenames, a.filenames, c.filenames, where);
    return encode_pathc(table);
}

Bytes merge_icons(const Bytes& raw_before, const Bytes& raw_after, const Bytes& raw_current, const std::string& where) {
    using Row = std::pair<std::string, Bytes>;  // lower-case name, element bytes
    const auto parts = [&](const Bytes& data) {
        IconRegistry registry;
        try {
            registry = parse_icon_registry(data);
        } catch (const FormatError& error) {
            throw OverlayConflict("Unsupported icon registry in " + where + ": " + error.what());
        }
        std::vector<Row> rows;
        for (const auto& texture : registry.textures) rows.emplace_back(lower_ascii(texture.name), texture.raw);
        return std::make_pair(std::move(registry.remainder), std::move(rows));
    };
    const auto b = parts(raw_before), a = parts(raw_after), c = parts(raw_current);
    auto out = merge_value(b.first, a.first, c.first, where);
    const auto records = merge_records(b.second, a.second, c.second, [](const Row& row) { return row.first; }, where);
    const auto newline = bytes_of(contains(raw_current, "\r\n") ? "\r\n" : "\n");
    for (std::size_t i = 0; i < records.size(); ++i) {
        if (i) append(out, newline);
        append(out, records[i].second);
    }
    append(out, newline);
    return out;
}

}  // namespace

FileMap merge_overlay_files(const FileMap& before, const FileMap& after, const FileMap& current) {
    FileMap result = current;
    std::vector<std::string> paths;
    std::set<std::string> listed, done;
    for (const auto* files : {&before, &after})
        for (const auto& item : files->items())
            if (listed.insert(item.first).second) paths.push_back(item.first);
    for (const auto& path : paths) {
        if (done.count(path)) continue;
        const auto b = before.get(path), a = after.get(path), c = current.get(path);
        try {
            result.set(path, merge_blob(b, a, c, path));
            continue;
        } catch (const OverlayConflict&) {
            if (!b || !a || !c) throw;
        }
        std::string body;
        if (ends_with(path, ".staticinfoheader") || ends_with(path, ".pabgh"))
            body = replace_all(replace_all(path, ".staticinfoheader", ".staticinfobody"), ".pabgh", ".pabgb");
        else if (ends_with(path, ".staticinfobody") || ends_with(path, ".pabgb"))
            body = path;
        if (!body.empty()) {
            const auto head = replace_all(replace_all(body, ".staticinfobody", ".staticinfoheader"), ".pabgb", ".pabgh");
            for (const auto* files : {&before, &after, &current})
                if (!files->get(body) || !files->get(head)) throw OverlayConflict("Both table files are required to compose " + body + ".");
            auto [payload, header] = merge_table_pair(before, after, current, body, head);
            result.set(body, blob(std::move(payload)));
            result.set(head, blob(std::move(header)));
            done.insert(body);
            done.insert(head);
        } else if (ends_with(path, ".paloc")) {
            result.set(path, blob(merge_paloc(*b, *a, *c, path)));
        } else if (ends_with(path, ".pappt")) {
            result.set(path, blob(merge_pappt(*b, *a, *c, path)));
        } else if (path == "meta/0.pathc") {
            result.set(path, blob(merge_pathc(*b, *a, *c, path)));
        } else if (path == "ui/xml/texture/cd_item_icon.xml") {
            result.set(path, blob(merge_icons(*b, *a, *c, path)));
        } else {
            throw OverlayConflict("Overlay conflict in " + path + "; overlapping file edits cannot be separated safely.");
        }
    }
    return result;
}

}  // namespace cdmw::compose
