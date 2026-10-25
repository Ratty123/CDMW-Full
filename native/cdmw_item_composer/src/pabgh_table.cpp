// structured_binary_editor.parse_pabgh_table and PabghTable.row_spans, heuristics included.
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {

constexpr std::size_t count_widths[] = {1, 2, 4};
constexpr std::size_t key_widths[] = {1, 2, 4, 8, 12};

PabghRow make_row(const Bytes& header, std::size_t index, std::size_t at, std::size_t key_width, std::size_t offset_at) {
    PabghRow row;
    row.index = index;
    row.key = slice(header, at, at + key_width);
    row.row_id = static_cast<std::uint32_t>(le(row.key.data(), std::min<std::size_t>(row.key.size(), 4)));
    row.offset = u32(header, offset_at);
    return row;
}

// _parse_pabgh_row_directory: resolve count and key widths against the payload's inline keys.
std::optional<PabghTable> parse_directory(const Bytes& header, const Bytes& payload) {
    for (const auto count_width : count_widths) {
        if (header.size() < count_width) continue;
        const auto count = le(header.data(), count_width);
        if (count == 0) continue;
        const std::size_t remainder = header.size() - count_width;
        if (remainder % count) continue;
        const std::size_t row_size = static_cast<std::size_t>(remainder / count);
        if (row_size < 4 || std::find(std::begin(key_widths), std::end(key_widths), row_size - 4) == std::end(key_widths)) continue;
        const std::size_t key_width = row_size - 4;
        std::vector<PabghRow> rows;
        std::size_t cursor = count_width;
        std::int64_t previous = -1;
        bool usable = true;
        for (std::size_t index = 0; index < count; ++index) {
            auto row = make_row(header, index, cursor, key_width, cursor + key_width);
            if (static_cast<std::int64_t>(row.offset) <= previous) {
                usable = false;
                break;
            }
            previous = row.offset;
            rows.push_back(std::move(row));
            cursor += row_size;
        }
        if (!usable || rows.empty()) continue;
        if (rows.front().offset != 0 || rows.back().offset >= payload.size()) continue;
        const bool inline_keys = std::all_of(rows.begin(), rows.end(), [&](const PabghRow& row) {
            return slice(payload, row.offset, std::size_t(row.offset) + key_width) == row.key;
        });
        if (!inline_keys) continue;
        PabghTable table;
        table.row_size = row_size;
        table.rows = std::move(rows);
        table.header_size = count_width;
        table.key_width = key_width;
        return table;
    }
    return std::nullopt;
}

PabghTable fixed_rows(const Bytes& header, std::size_t count, std::size_t row_size) {
    PabghTable table;
    table.row_size = row_size;
    table.key_width = row_size - 4;
    std::size_t at = 2;
    for (std::size_t index = 0; index < count; ++index, at += row_size)
        table.rows.push_back(make_row(header, index, at, row_size == 5 ? 1 : 4, at + row_size - 4));
    return table;
}

}  // namespace

PabghTable parse_pabgh_table(const Bytes& header, const Bytes* payload) {
    if (header.size() < 2) throw FormatError("PABGH table is too short to contain a row count.");
    const std::size_t count = u16(header, 0);
    for (const std::size_t row_size : {std::size_t(8), std::size_t(5)}) {
        if (count > 0 && 2 + count * row_size == header.size()) return fixed_rows(header, count, row_size);
    }
    if (payload) {
        if (auto resolved = parse_directory(header, *payload)) return std::move(*resolved);
    }
    // Neither exact nor resolved: the larger number of in-range offsets wins, then the
    // smaller row.
    std::optional<std::pair<std::size_t, std::size_t>> best;  // (valid offsets, row size)
    for (const std::size_t row_size : {std::size_t(5), std::size_t(8)}) {
        if (count == 0 || 2 + count * row_size > header.size()) continue;
        std::size_t valid = 0;
        for (std::size_t index = 0, at = 2; index < count; ++index, at += row_size)
            valid += u32(header, at + row_size - 4) <= header.size();
        if (!best || valid > best->first) best = std::make_pair(valid, row_size);
    }
    if (!best) throw FormatError("PABGH row table count " + std::to_string(count) + " does not fit the payload.");
    return fixed_rows(header, count, best->second);
}

std::vector<RowSpan> row_spans(const PabghTable& table, std::size_t payload_length) {
    std::vector<const PabghRow*> ordered;
    for (const auto& row : table.rows) ordered.push_back(&row);
    std::stable_sort(ordered.begin(), ordered.end(), [](const PabghRow* x, const PabghRow* y) { return x->offset < y->offset; });
    std::vector<const PabghRow*> usable;
    for (const auto* row : ordered)
        if (row->offset < payload_length) usable.push_back(row);
    std::vector<RowSpan> spans;
    for (std::size_t index = 0; index < usable.size(); ++index)
        spans.push_back({usable[index], usable[index]->offset, index + 1 < usable.size() ? usable[index + 1]->offset : payload_length});
    return spans;
}

}  // namespace cdmw::compose::detail
