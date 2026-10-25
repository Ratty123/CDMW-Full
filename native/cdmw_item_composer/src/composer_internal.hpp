// Internal codecs and merge primitives. Each mirrors the named Python function; keep the
// two in step, and prove it with tests/test_native_overlay_merge.py.
#pragma once
#include "cdmw_composer/composer.hpp"

#include <algorithm>
#include <array>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <type_traits>

namespace cdmw::compose::detail {

// ---- bytes -------------------------------------------------------------------------------

inline std::uint64_t le(const std::uint8_t* data, std::size_t width) {
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < width; ++i) value |= static_cast<std::uint64_t>(data[i]) << (8 * i);
    return value;
}
inline std::uint16_t u16(const Bytes& data, std::size_t at) { return static_cast<std::uint16_t>(le(data.data() + at, 2)); }
inline std::uint32_t u32(const Bytes& data, std::size_t at) { return static_cast<std::uint32_t>(le(data.data() + at, 4)); }
inline std::uint64_t u64(const Bytes& data, std::size_t at) { return le(data.data() + at, 8); }
inline void put_le(Bytes& out, std::uint64_t value, std::size_t width) {
    for (std::size_t i = 0; i < width; ++i) out.push_back(static_cast<std::uint8_t>(value >> (8 * i)));
}
inline void put_u16(Bytes& out, std::uint16_t value) { put_le(out, value, 2); }
inline void put_u32(Bytes& out, std::uint32_t value) { put_le(out, value, 4); }
inline void put_u64(Bytes& out, std::uint64_t value) { put_le(out, value, 8); }
inline void append(Bytes& out, const Bytes& value) { out.insert(out.end(), value.begin(), value.end()); }
// Python slicing: both ends clamp to the buffer.
inline Bytes slice(const Bytes& data, std::size_t begin, std::size_t end) {
    end = std::min(end, data.size());
    begin = std::min(begin, end);
    return Bytes(data.begin() + static_cast<std::ptrdiff_t>(begin), data.begin() + static_cast<std::ptrdiff_t>(end));
}
inline Bytes bytes_of(std::string_view text) { return Bytes(text.begin(), text.end()); }
inline std::string text_of(const Bytes& data) { return std::string(data.begin(), data.end()); }
// Byte comparisons: a `char` above 0x7F is negative, so compare as unsigned.
inline bool same_byte(char text, std::uint8_t byte) { return static_cast<std::uint8_t>(text) == byte; }
inline bool starts_with(const Bytes& data, std::string_view prefix) {
    return data.size() >= prefix.size() &&
           std::equal(prefix.begin(), prefix.end(), data.begin(), [](char a, std::uint8_t b) { return same_byte(a, b); });
}
inline bool contains(const Bytes& data, std::string_view needle) {
    return std::search(data.begin(), data.end(), needle.begin(), needle.end(),
                       [](std::uint8_t a, char b) { return same_byte(b, a); }) != data.end();
}

// archive_format's try_decode_text_like_archive_data(data) is not None.
bool text_like(const Bytes& data);

// UTF-8 text <-> paths (C++20 spells UTF-8 as char8_t).
inline std::string utf8_of(const std::filesystem::path& path) {
    const auto text = path.u8string();
    return std::string(text.begin(), text.end());
}
inline std::filesystem::path path_of(std::string_view text) { return std::filesystem::path(std::u8string(text.begin(), text.end())); }

// Python's strict UTF-8 decoder: well-formed sequences only (no overlongs, surrogates or
// code points past U+10FFFF).
bool valid_utf8(const std::uint8_t* data, std::size_t size);
inline bool valid_utf8(const Bytes& data) { return valid_utf8(data.data(), data.size()); }
// Decimal text of an unsigned little-endian integer of any width, as Python's int.from_bytes.
std::string decimal_le(const Bytes& data);
// The record-key spelling Python's f-strings produce for a bytes key.
std::string python_bytes_repr(const Bytes& data);
// Python str.replace: every occurrence.
std::string replace_all(std::string text, std::string_view from, std::string_view to);
inline bool ends_with(std::string_view text, std::string_view suffix) {
    return text.size() >= suffix.size() && text.substr(text.size() - suffix.size()) == suffix;
}

// ---- merge primitives (overlay_merge._value / _indexed / _records) -----------------------

[[noreturn]] inline void same_record(const std::string& where) {
    throw OverlayConflict("Overlay conflict in " + where + "; both installs change the same record.");
}

// _value on values that always exist.
template <class T>
T merge_value(const T& before, const T& after, const T& current, const std::string& where) {
    if (before == after || current == after) return current;
    if (current == before) return after;
    same_record(where);
}

// _value on values that may be missing (None).
template <class T>
std::optional<T> merge_optional(const T* before, const T* after, const T* current, const std::string& where) {
    const auto equal = [](const T* x, const T* y) { return x == y || (x && y && *x == *y); };
    if (equal(before, after) || equal(current, after)) return current ? std::optional<T>(*current) : std::nullopt;
    if (equal(current, before)) return after ? std::optional<T>(*after) : std::nullopt;
    same_record(where);
}

inline std::string describe_key(const Bytes& key) { return text_of(key); }
inline std::string describe_key(const std::string& key) { return key; }
inline std::string describe_key(std::uint64_t key) { return std::to_string(key); }

// _records: three-way merge of a keyed collection. Repeated keys pair by occurrence, and the
// result follows current's order, then after's additions, then before's.
template <class T, class KeyFn, class MergeFn>
std::vector<T> merge_records(const std::vector<T>& before, const std::vector<T>& after, const std::vector<T>& current,
                             KeyFn key, const std::string& where, MergeFn merge) {
    using Key = std::decay_t<decltype(key(std::declval<const T&>()))>;
    using Identity = std::pair<Key, std::size_t>;
    struct Indexed {
        std::vector<Identity> order;
        std::map<Identity, const T*> rows;
    };
    const auto index = [&](const std::vector<T>& rows) {
        Indexed result;
        std::map<Key, std::size_t> counts;
        for (const auto& row : rows) {
            Identity identity{key(row), 0};
            identity.second = counts[identity.first]++;
            result.rows.emplace(identity, &row);
            result.order.push_back(std::move(identity));
        }
        return result;
    };
    const auto b = index(before), a = index(after), c = index(current);
    const auto find = [](const Indexed& table, const Identity& identity) -> const T* {
        const auto found = table.rows.find(identity);
        return found == table.rows.end() ? nullptr : found->second;
    };
    std::set<Identity> seen;
    std::vector<T> result;
    for (const auto* order : {&c.order, &a.order, &b.order}) {
        for (const auto& identity : *order) {
            if (!seen.insert(identity).second) continue;
            auto value = merge(find(b, identity), find(a, identity), find(c, identity),
                               where + " [" + describe_key(identity.first) + "]");
            if (value) result.push_back(std::move(*value));
        }
    }
    return result;
}

template <class T, class KeyFn>
std::vector<T> merge_records(const std::vector<T>& before, const std::vector<T>& after, const std::vector<T>& current,
                             KeyFn key, const std::string& where) {
    return merge_records(before, after, current, key, where,
                         [](const T* b, const T* a, const T* c, const std::string& at) { return merge_optional(b, a, c, at); });
}

// ---- structured_binary_editor: .pabgh row directories ------------------------------------

struct PabghRow {
    std::size_t index{};
    std::uint32_t row_id{};
    std::uint32_t offset{};
    Bytes key;
};
struct PabghTable {
    std::size_t row_size{};
    std::vector<PabghRow> rows;
    std::size_t header_size = 2;
    std::size_t key_width = 4;
};
struct RowSpan {
    const PabghRow* row;
    std::size_t start, end;
};
PabghTable parse_pabgh_table(const Bytes& header, const Bytes* payload);
std::vector<RowSpan> row_spans(const PabghTable& table, std::size_t payload_length);

// ---- storeinfo_table ---------------------------------------------------------------------

struct StockEntry {
    std::uint16_t store_key{};
    std::uint64_t min_price_percent{}, max_price_percent{};
    std::uint32_t count{};
    std::int32_t threshold{};
    std::uint64_t stock_index{}, order_index{};
    std::int32_t important_save_index{};
    Bytes flags, drop_bytes, after_bytes;
    std::uint32_t item_key{};
    std::optional<Bytes> option_block;
    std::vector<Bytes> order_records;
    std::int64_t offset = -1, end = -1;
    Bytes condition_data;

    bool is_sellable() const { return flags.at(1) != 0; }
    bool is_buyable() const { return flags.at(2) != 0; }
    bool operator==(const StockEntry&) const = default;
};
struct StoreRow {
    Bytes raw;
    std::uint16_t key{};
    std::string name;
    Bytes prefix;
    std::uint64_t buyable_count{}, sellable_count{};
    std::uint8_t store_type{};
    std::vector<StockEntry> entries;
    Bytes tail;
    std::size_t head_offset{};
    bool current_layout = false;
};
StoreRow parse_store_row(const Bytes& raw, bool current_layout);
Bytes encode_store_row(const StoreRow& row);

// ---- itemgroupinfo_table -----------------------------------------------------------------

struct ItemGroupRow {
    Bytes raw;
    std::uint16_t key{};
    std::string name;
    Bytes prefix;
    std::vector<std::uint16_t> subgroups;
    std::vector<std::uint32_t> members;
    Bytes tail;
};
ItemGroupRow parse_item_group_row(const Bytes& raw);
Bytes encode_item_group_row(const ItemGroupRow& row);

// ---- paloc_format ------------------------------------------------------------------------

struct LocalizationEntry {
    std::uint32_t category{};
    Bytes key, text;  // validated UTF-8, kept as bytes
    std::uint32_t reserved{};
    bool operator==(const LocalizationEntry&) const = default;
};
struct LocalizationTable {
    std::vector<LocalizationEntry> entries;
    Bytes source_container;
};
LocalizationTable parse_paloc(const Bytes& data);
Bytes encode_paloc(const LocalizationTable& table);
LocalizationTable add_localization_entries(LocalizationTable table, const std::vector<LocalizationEntry>& additions);

// ---- pappt_format ------------------------------------------------------------------------

struct PartPrefabPart {
    Bytes name;
    std::uint8_t flag{};
    bool operator==(const PartPrefabPart&) const = default;
};
struct PartPrefabRecord {
    Bytes stem, folder, sockets_path, extra;
    std::uint8_t flag{};
    std::vector<PartPrefabPart> parts;
    bool operator==(const PartPrefabRecord&) const = default;
};
struct HeadPrefabRecord {
    Bytes stem, folder;
    bool operator==(const HeadPrefabRecord&) const = default;
};
struct PartPrefabTable {
    std::vector<PartPrefabRecord> records;
    std::vector<HeadPrefabRecord> head_records;
    Bytes reserved;
    Bytes tag_prefix;
};
PartPrefabTable parse_pappt(const Bytes& data);
Bytes encode_pappt(const PartPrefabTable& table);

// ---- pathc_format ------------------------------------------------------------------------

struct PathcEntry {
    std::uint32_t checksum{};
    std::uint64_t header_index{};
    std::uint8_t collision_start{}, collision_end{};
    Bytes block_infos;
    bool is_direct() const { return header_index != 0xFFFF; }
};
struct PathcTable {
    std::uint64_t reserved{};
    std::uint32_t header_size{};
    std::vector<Bytes> headers;
    std::vector<PathcEntry> entries;
    std::vector<Bytes> collisions;
    Bytes filenames;
};
PathcTable parse_pathc(const Bytes& data);
Bytes encode_pathc(const PathcTable& table);

// ---- item_icon_registry ------------------------------------------------------------------

struct IconTexture {
    std::string name, filename;
    Bytes raw;
};
struct IconRegistry {
    std::vector<IconTexture> textures;
    Bytes remainder;
};
IconRegistry parse_icon_registry(const Bytes& data);

}  // namespace cdmw::compose::detail
