// itemgroupinfo_table.parse_item_group_row / encode_item_group_row.
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {
constexpr std::uint8_t tag[] = {0x08, 0x80, 0x00, 0x00, 0x00};
constexpr std::size_t tail_min = 15;
}  // namespace

ItemGroupRow parse_item_group_row(const Bytes& data) {
    if (data.size() < 6) throw FormatError("row is too short for a key and a name length");
    ItemGroupRow row;
    row.key = u16(data, 0);
    const std::uint64_t length = u32(data, 2);
    std::uint64_t at = 6 + length;
    if (at + 1 + sizeof tag + 8 > data.size())
        throw FormatError("item group " + std::to_string(row.key) + ": the name runs past the row");
    row.name.assign(data.begin() + 6, data.begin() + static_cast<std::ptrdiff_t>(at));
    const auto where = "item group '" + row.name + "' (" + std::to_string(row.key) + ")";
    if (data[at] != 0 || !std::equal(std::begin(tag), std::end(tag), data.begin() + static_cast<std::ptrdiff_t>(at + 1)))
        throw FormatError(where + ": expected the NUL and 08 80 tag after the name");
    at += 1 + sizeof tag;
    const auto again = u32(data, static_cast<std::size_t>(at));
    const std::uint64_t digits = u32(data, static_cast<std::size_t>(at + 4));
    if (again != row.key) throw FormatError(where + ": the repeated key reads " + std::to_string(again));
    at += 8 + digits;
    if (at + 4 > data.size()) throw FormatError(where + ": the digit string runs past the row");
    row.prefix = slice(data, 0, static_cast<std::size_t>(at));
    const std::uint64_t subgroups = u32(data, static_cast<std::size_t>(at));
    at += 4;
    if (at + 2 * subgroups + 4 > data.size()) throw FormatError(where + ": " + std::to_string(subgroups) + " sub-groups run past the row");
    for (std::uint64_t i = 0; i < subgroups; ++i) row.subgroups.push_back(u16(data, static_cast<std::size_t>(at + 2 * i)));
    at += 2 * subgroups;
    const std::uint64_t members = u32(data, static_cast<std::size_t>(at));
    at += 4;
    if (at + 4 * members > data.size()) throw FormatError(where + ": " + std::to_string(members) + " members run past the row");
    for (std::uint64_t i = 0; i < members; ++i) row.members.push_back(u32(data, static_cast<std::size_t>(at + 4 * i)));
    at += 4 * members;
    row.tail = slice(data, static_cast<std::size_t>(at), data.size());
    if (row.tail.size() < tail_min || row.tail.size() != tail_min + std::uint64_t(u32(row.tail, 0)))
        throw FormatError(where + ": " + std::to_string(row.tail.size()) + " bytes follow the member list, expected 15 plus the count the tail opens with");
    row.raw = data;
    return row;
}

Bytes encode_item_group_row(const ItemGroupRow& row) {
    Bytes out = row.prefix;
    put_u32(out, static_cast<std::uint32_t>(row.subgroups.size()));
    for (const auto sub : row.subgroups) put_u16(out, sub);
    put_u32(out, static_cast<std::uint32_t>(row.members.size()));
    for (const auto member : row.members) put_u32(out, member);
    append(out, row.tail);
    return out;
}

}  // namespace cdmw::compose::detail
