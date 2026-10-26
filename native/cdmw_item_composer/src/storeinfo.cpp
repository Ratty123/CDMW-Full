// storeinfo_table.parse_store_row / encode_store_row.
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {

constexpr std::size_t head_size = 13;
constexpr std::size_t fixed_size = 0x77;
constexpr std::size_t option_size = 13;
constexpr std::size_t order_record = 12;
constexpr std::size_t item_a = 0x2B;
constexpr std::size_t item_b = 0x66;
constexpr std::size_t option_flag = 0x72;
constexpr std::size_t max_order_records = 8;

bool known_store_type(std::uint8_t value) { return value == 0 || value == 1 || value == 2 || value == 4 || value == 5; }

[[noreturn]] void store_error(const std::string& reason) { throw FormatError(reason); }

std::optional<std::size_t> entry_length(const Bytes& raw, std::size_t offset, std::size_t extra) {
    if (offset + fixed_size > raw.size()) return std::nullopt;
    const auto flag = raw[offset + option_flag];
    std::size_t fixed;
    if (flag == 0) fixed = fixed_size + extra;
    else if (flag == 1) fixed = fixed_size + option_size + extra;
    else return std::nullopt;
    if (offset + fixed > raw.size()) return std::nullopt;
    const auto records = u32(raw, offset + fixed - 4);
    if (records > max_order_records) return std::nullopt;
    const auto length = fixed + records * order_record;
    if (offset + length > raw.size()) return std::nullopt;
    return length;
}

bool looks_like_first_entry(const Bytes& raw, std::size_t offset, std::uint16_t key, std::size_t extra) {
    if (offset + fixed_size > raw.size()) return false;
    if (u16(raw, offset) != key) return false;
    if (u32(raw, offset + item_a) != u32(raw, offset + item_b)) return false;
    if (u32(raw, offset + 0x1A) != 0) return false;
    if (!entry_length(raw, offset, extra)) return false;
    return known_store_type(raw[offset - 5]) && u32(raw, offset - 4) >= 1;
}

StockEntry parse_entry(const Bytes& raw, std::size_t offset, std::size_t length, std::size_t extra) {
    StockEntry entry;
    entry.store_key = u16(raw, offset);
    entry.min_price_percent = u64(raw, offset + 2);
    entry.max_price_percent = u64(raw, offset + 10);
    entry.count = u32(raw, offset + 0x12);
    entry.threshold = static_cast<std::int32_t>(u32(raw, offset + 0x16));
    entry.stock_index = u32(raw, offset + 0x1A);
    entry.order_index = u32(raw, offset + 0x1E);
    entry.important_save_index = static_cast<std::int32_t>(u32(raw, offset + 0x22));
    entry.flags = slice(raw, offset + 0x26, offset + 0x2B);
    entry.item_key = u32(raw, offset + item_a);
    entry.drop_bytes = slice(raw, offset + item_a + 4, offset + item_b);
    entry.after_bytes = slice(raw, offset + item_b + 4, offset + option_flag);
    std::size_t at = offset + option_flag + 1;
    if (raw[offset + option_flag] == 1) {
        entry.option_block = slice(raw, at, at + option_size);
        at += option_size;
    }
    entry.condition_data = slice(raw, at, at + extra);
    at += extra;
    const auto records = u32(raw, at);
    at += 4;
    for (std::uint32_t i = 0; i < records; ++i) entry.order_records.push_back(slice(raw, at + i * order_record, at + (i + 1) * order_record));
    entry.offset = static_cast<std::int64_t>(offset);
    entry.end = static_cast<std::int64_t>(offset + length);
    return entry;
}

std::optional<std::size_t> find_empty_head(const Bytes& raw, std::size_t name_end) {
    for (std::size_t offset = name_end; offset + head_size <= raw.size(); ++offset) {
        if (!std::all_of(raw.begin() + static_cast<std::ptrdiff_t>(offset), raw.begin() + static_cast<std::ptrdiff_t>(offset + 8), [](std::uint8_t b) { return b == 0; }) ||
            !std::all_of(raw.begin() + static_cast<std::ptrdiff_t>(offset + 9), raw.begin() + static_cast<std::ptrdiff_t>(offset + 13), [](std::uint8_t b) { return b == 0; }))
            continue;
        if (!known_store_type(raw[offset + 8])) continue;
        if (raw.size() - (offset + head_size) <= 32) return offset;
    }
    return std::nullopt;
}

std::uint32_t fits_u32(std::uint64_t value, const char* what) {
    if (value > 0xFFFFFFFFull) store_error(std::string(what) + " " + std::to_string(value) + " does not fit a u32");
    return static_cast<std::uint32_t>(value);
}

Bytes encode_stock_entry(const StockEntry& entry) {
    if (entry.flags.size() != 5) store_error("a stock entry carries five flag bytes");
    if (entry.drop_bytes.size() != item_b - (item_a + 4)) store_error("drop data is 55 bytes");
    if (entry.after_bytes.size() != option_flag - (item_b + 4)) store_error("the bytes after the second item key are 8 bytes");
    if (entry.option_block && entry.option_block->size() != option_size) store_error("the option block is 13 bytes");
    for (const auto& record : entry.order_records)
        if (record.size() != order_record) store_error("order-count records are 12 bytes");
    if (entry.condition_data.size() != 0 && entry.condition_data.size() != 8)
        store_error("stock condition data must be empty (legacy) or eight bytes (current)");
    Bytes out;
    put_u16(out, entry.store_key);
    put_u64(out, entry.min_price_percent);
    put_u64(out, entry.max_price_percent);
    put_u32(out, entry.count);
    put_u32(out, static_cast<std::uint32_t>(entry.threshold));
    put_u32(out, fits_u32(entry.stock_index, "stock index"));
    put_u32(out, fits_u32(entry.order_index, "order index"));
    put_u32(out, static_cast<std::uint32_t>(entry.important_save_index));
    append(out, entry.flags);
    put_u32(out, entry.item_key);
    append(out, entry.drop_bytes);
    put_u32(out, entry.item_key);
    append(out, entry.after_bytes);
    if (entry.option_block) {
        out.push_back(1);
        append(out, *entry.option_block);
    } else {
        out.push_back(0);
    }
    append(out, entry.condition_data);
    put_u32(out, static_cast<std::uint32_t>(entry.order_records.size()));
    for (const auto& record : entry.order_records) append(out, record);
    return out;
}

}  // namespace

StoreRow parse_store_row(const Bytes& data, bool current_layout) {
    const std::size_t extra = current_layout ? 8 : 0;
    if (data.size() < 6) store_error("row is too short for a key and a name length");
    const auto row_key = u16(data, 0);
    const std::uint64_t length = u32(data, 2);
    if (6 + length + 1 > data.size()) store_error("store name of " + std::to_string(length) + " bytes runs past the row");
    const std::string name(data.begin() + 6, data.begin() + 6 + static_cast<std::ptrdiff_t>(length));
    const std::size_t name_end = 6 + static_cast<std::size_t>(length) + 1;
    const auto where = "store '" + name + "' (" + std::to_string(row_key) + ")";

    std::optional<std::size_t> head;
    for (std::size_t offset = name_end + head_size; offset + fixed_size <= data.size(); ++offset) {
        if (looks_like_first_entry(data, offset, row_key, extra)) {
            head = offset - head_size;
            break;
        }
    }
    if (!head) {
        head = find_empty_head(data, name_end);
        if (!head) store_error(where + ": no stock list found");
    }
    StoreRow row;
    row.buyable_count = u32(data, *head);
    row.sellable_count = u32(data, *head + 4);
    row.store_type = data[*head + 8];
    const auto total = u32(data, *head + 9);
    if (!known_store_type(row.store_type)) store_error(where + ": unknown store type " + std::to_string(row.store_type));

    std::size_t at = *head + head_size;
    for (std::uint32_t index = 0; index < total; ++index) {
        const auto size = entry_length(data, at, extra);
        if (!size) store_error(where + ": stock entry " + std::to_string(index) + " does not read");
        auto entry = parse_entry(data, at, *size, extra);
        if (entry.store_key != row_key) store_error(where + ": entry " + std::to_string(index) + " names store " + std::to_string(entry.store_key));
        if (entry.item_key != u32(data, at + item_b)) store_error(where + ": entry " + std::to_string(index) + " does not repeat its item key");
        row.entries.push_back(std::move(entry));
        at += *size;
    }
    row.raw = data;
    row.key = row_key;
    row.name = name;
    row.prefix = slice(data, 0, *head);
    row.tail = slice(data, at, data.size());
    row.head_offset = *head;
    row.current_layout = current_layout;
    return row;
}

Bytes encode_store_row(const StoreRow& row) {
    Bytes out = row.prefix;
    put_u32(out, fits_u32(row.buyable_count, "buyable count"));
    put_u32(out, fits_u32(row.sellable_count, "sellable count"));
    out.push_back(row.store_type);
    put_u32(out, static_cast<std::uint32_t>(row.entries.size()));
    for (const auto& entry : row.entries) {
        if (entry.condition_data.size() != (row.current_layout ? 8u : 0u)) store_error("stock entry and store use different layouts");
        append(out, encode_stock_entry(entry));
    }
    append(out, row.tail);
    return out;
}

}  // namespace cdmw::compose::detail
