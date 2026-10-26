// paloc_format.parse_paloc / encode_paloc / add_localization_entries, 512-byte LZ4 container included.
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {

constexpr std::size_t footer = 4;
constexpr std::size_t record_head = 12;
constexpr std::size_t container_header = 512;
constexpr std::uint64_t max_container_payload = 256ull * 1024 * 1024;

Bytes container_payload(const Bytes& data) {
    if (data.size() < container_header) throw FormatError("PALOC container header is truncated");
    const auto version = u32(data, 5), stored = u32(data, 9), payload_size = u32(data, 13);
    if (version != 0) throw FormatError("unsupported PALOC container version " + std::to_string(version));
    if (stored != data.size() - container_header) throw FormatError("PALOC container compressed size does not match its bytes");
    if (payload_size < footer || payload_size > max_container_payload) throw FormatError("PALOC container uncompressed size is out of bounds");
    try {
        return lz4::decompress(data.data() + container_header, data.size() - container_header, payload_size);
    } catch (const FormatError& error) {
        throw FormatError(std::string("PALOC container LZ4 decompression failed: ") + error.what());
    }
}

// str.isdigit on keys this port can classify: ASCII digits. A key of non-ASCII characters
// and ASCII digits alone might be Unicode digits to Python, which this port does not model.
bool numeric_key(const Bytes& key) {
    if (key.empty()) return false;
    bool ascii_only = true;
    for (const auto byte : key) {
        if (byte >= 0x80) ascii_only = false;
        else if (byte < '0' || byte > '9') return false;
    }
    if (!ascii_only) throw Unsupported("localization key may be a Unicode number");
    return true;
}

// int(a) < int(b) for ASCII digit strings of any length.
int compare_numbers(const Bytes& a, const Bytes& b) {
    auto x = std::find_if(a.begin(), a.end(), [](std::uint8_t c) { return c != '0'; });
    auto y = std::find_if(b.begin(), b.end(), [](std::uint8_t c) { return c != '0'; });
    const auto lx = a.end() - x, ly = b.end() - y;
    if (lx != ly) return lx < ly ? -1 : 1;
    for (; x != a.end(); ++x, ++y)
        if (*x != *y) return *x < *y ? -1 : 1;
    return 0;
}

}  // namespace

LocalizationTable parse_paloc(const Bytes& raw) {
    LocalizationTable table;
    const Bytes* data = &raw;
    Bytes decoded;
    if (starts_with(raw, "paloc")) {
        table.source_container = raw;
        decoded = container_payload(raw);
        data = &decoded;
    }
    if (data->size() < footer) throw FormatError("buffer is too short to hold a count");
    const auto declared = u32(*data, data->size() - footer);
    const std::size_t limit = data->size() - footer;
    std::size_t at = 0, records = 0;
    while (at < limit) {
        if (at + record_head > limit) throw FormatError("record header runs past the table");
        LocalizationEntry entry;
        entry.category = u32(*data, at);
        entry.reserved = u32(*data, at + 4);
        const std::uint64_t key_length = u32(*data, at + 8);
        at += record_head;
        if (at + key_length + 4 > limit) throw FormatError("key runs past the table");
        entry.key = slice(*data, at, at + static_cast<std::size_t>(key_length));
        at += static_cast<std::size_t>(key_length);
        const std::uint64_t text_length = u32(*data, at);
        at += 4;
        if (at + text_length > limit) throw FormatError("text runs past the table");
        entry.text = slice(*data, at, at + static_cast<std::size_t>(text_length));
        at += static_cast<std::size_t>(text_length);
        if (!valid_utf8(entry.key) || !valid_utf8(entry.text)) throw FormatError("record " + std::to_string(records) + " is not UTF-8");
        table.entries.push_back(std::move(entry));
        ++records;
    }
    if (records != declared)
        throw FormatError("the footer counts " + std::to_string(declared) + " records but the table walks " + std::to_string(records));
    return table;
}

Bytes encode_paloc(const LocalizationTable& table) {
    Bytes payload;
    for (const auto& entry : table.entries) {
        put_u32(payload, entry.category);
        put_u32(payload, entry.reserved);
        put_u32(payload, static_cast<std::uint32_t>(entry.key.size()));
        append(payload, entry.key);
        put_u32(payload, static_cast<std::uint32_t>(entry.text.size()));
        append(payload, entry.text);
    }
    put_u32(payload, static_cast<std::uint32_t>(table.entries.size()));
    if (table.source_container.empty()) return payload;
    if (payload == container_payload(table.source_container)) return table.source_container;
    if (payload.size() > max_container_payload) throw FormatError("PALOC container uncompressed size is out of bounds");
    const auto compressed = lz4::compress(payload.data(), payload.size());
    Bytes out = slice(table.source_container, 0, container_header);
    for (std::size_t i = 0; i < 4; ++i) {
        out[9 + i] = static_cast<std::uint8_t>(compressed.size() >> (8 * i));
        out[13 + i] = static_cast<std::uint8_t>(payload.size() >> (8 * i));
    }
    append(out, compressed);
    return out;
}

LocalizationTable add_localization_entries(LocalizationTable table, const std::vector<LocalizationEntry>& additions) {
    std::set<Bytes> existing, seen;
    for (const auto& entry : table.entries) existing.insert(entry.key);
    for (const auto& entry : additions) {
        if (entry.key.empty()) throw FormatError("a localization key cannot be empty");
        if (existing.count(entry.key)) throw FormatError("localization key '" + text_of(entry.key) + "' already exists in the table");
        if (!seen.insert(entry.key).second) throw FormatError("localization key '" + text_of(entry.key) + "' is repeated in the additions");
    }
    if (additions.empty()) return table;
    // The leading ascending run of numeric keys decides where a numeric addition goes.
    std::vector<std::pair<const Bytes*, std::size_t>> spine;
    for (std::size_t index = 0; index < table.entries.size(); ++index) {
        const auto& key = table.entries[index].key;
        if (!numeric_key(key)) continue;
        if (!spine.empty() && compare_numbers(key, *spine.back().first) <= 0) break;
        spine.emplace_back(&key, index);
    }
    std::vector<const LocalizationEntry*> numeric, named;
    for (const auto& entry : additions) (numeric_key(entry.key) ? numeric : named).push_back(&entry);
    // sorted(key=int, reverse=True) is stable: equal values keep their order.
    std::stable_sort(numeric.begin(), numeric.end(), [](const LocalizationEntry* x, const LocalizationEntry* y) {
        return compare_numbers(x->key, y->key) > 0;
    });
    std::vector<std::size_t> positions;
    for (const auto* entry : numeric) {
        // bisect_right: the first spine value greater than the new key.
        const auto slot = static_cast<std::size_t>(std::upper_bound(spine.begin(), spine.end(), entry->key,
            [](const Bytes& value, const std::pair<const Bytes*, std::size_t>& item) { return compare_numbers(value, *item.first) < 0; }) - spine.begin());
        positions.push_back(slot < spine.size() ? spine[slot].second : spine.empty() ? table.entries.size() : spine.back().second + 1);
    }
    auto merged = table.entries;
    // Largest first at positions of the unedited table, so earlier positions stay valid.
    for (std::size_t i = 0; i < numeric.size(); ++i)
        merged.insert(merged.begin() + static_cast<std::ptrdiff_t>(positions[i]), *numeric[i]);
    for (const auto* entry : named) merged.push_back(*entry);
    table.entries = std::move(merged);
    return table;
}

}  // namespace cdmw::compose::detail
