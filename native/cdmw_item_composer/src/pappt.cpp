// pappt_format.parse_pappt / encode_pappt: both record layouts (no tag prefix, and 01).
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {

Bytes read_str(const Bytes& data, std::size_t& at, const std::string& what) {
    if (at >= data.size()) throw FormatError(what + " runs past the table");
    const std::size_t length = data[at];
    const std::size_t end = at + 1 + length;
    if (length < 1 || end > data.size()) throw FormatError(what + " has length " + std::to_string(length) + ", which does not fit the table");
    if (data[end - 1] != 0) throw FormatError(what + " is not NUL-terminated");
    auto text = slice(data, at + 1, end - 1);
    if (!valid_utf8(text)) throw FormatError(what + " is not UTF-8");
    at = end;
    return text;
}

void write_str(Bytes& out, const Bytes& text, const std::string& what) {
    if (text.size() + 1 > 255) throw FormatError(what + " is " + std::to_string(text.size() + 1) + " bytes with its NUL; the format allows 255");
    out.push_back(static_cast<std::uint8_t>(text.size() + 1));
    append(out, text);
    out.push_back(0);
}

PartPrefabTable parse_layout(const Bytes& data, const Bytes& tag_prefix) {
    if (data.size() < 12) throw FormatError("buffer is too short to hold the header");
    PartPrefabTable table;
    table.reserved = slice(data, 0, 8);
    table.tag_prefix = tag_prefix;
    const auto count = u32(data, 8);
    std::size_t at = 12;
    for (std::uint32_t index = 0; index < count; ++index) {
        const auto what = "record " + std::to_string(index);
        PartPrefabRecord record;
        record.stem = read_str(data, at, what + " stem");
        record.folder = read_str(data, at, what + " folder");
        record.sockets_path = read_str(data, at, what + " sockets path");
        if (!tag_prefix.empty()) {
            const auto end = at + tag_prefix.size();
            if (end > data.size() || !std::equal(tag_prefix.begin(), tag_prefix.end(), data.begin() + static_cast<std::ptrdiff_t>(at)))
                throw FormatError(what + " tag prefix does not match");
            at = end;
        }
        record.extra = read_str(data, at, what + " tag");
        if (at + 2 > data.size()) throw FormatError(what + " flags run past the table");
        record.flag = data[at];
        const auto parts = data[at + 1];
        at += 2;
        for (std::uint32_t part = 0; part < parts; ++part) {
            PartPrefabPart item;
            item.name = read_str(data, at, what + " part " + std::to_string(part));
            if (at >= data.size()) throw FormatError(what + " part " + std::to_string(part) + " flag runs past the table");
            item.flag = data[at++];
            record.parts.push_back(std::move(item));
        }
        table.records.push_back(std::move(record));
    }
    if (at + 4 > data.size()) throw FormatError("head record count runs past the table");
    const auto heads = u32(data, at);
    at += 4;
    for (std::uint32_t index = 0; index < heads; ++index) {
        HeadPrefabRecord head;
        head.stem = read_str(data, at, "head record " + std::to_string(index) + " stem");
        head.folder = read_str(data, at, "head record " + std::to_string(index) + " folder");
        table.head_records.push_back(std::move(head));
    }
    if (at != data.size()) throw FormatError("the walk ends before the end of the table");
    return table;
}

}  // namespace

PartPrefabTable parse_pappt(const Bytes& data) {
    std::string failures;
    for (const auto& prefix : {Bytes{}, Bytes{1}}) {
        try {
            return parse_layout(data, prefix);
        } catch (const FormatError& error) {
            failures += std::string(failures.empty() ? "original layout: " : "; game 2.00.00 layout: ") + error.what();
        }
    }
    throw FormatError("unsupported part-prefab table layout; " + failures);
}

Bytes encode_pappt(const PartPrefabTable& table) {
    if (table.reserved.size() != 8) throw FormatError("the reserved header is eight bytes");
    if (!(table.tag_prefix.empty() || table.tag_prefix == Bytes{1})) throw FormatError("the per-record tag prefix is not a supported part-prefab layout");
    Bytes out = table.reserved;
    put_u32(out, static_cast<std::uint32_t>(table.records.size()));
    for (std::size_t index = 0; index < table.records.size(); ++index) {
        const auto& record = table.records[index];
        const auto what = "record " + std::to_string(index);
        write_str(out, record.stem, what + " stem");
        write_str(out, record.folder, what + " folder");
        write_str(out, record.sockets_path, what + " sockets path");
        append(out, table.tag_prefix);
        write_str(out, record.extra, what + " tag");
        if (record.parts.size() > 0xFF) throw FormatError(what + " part count does not fit a byte");
        out.push_back(record.flag);
        out.push_back(static_cast<std::uint8_t>(record.parts.size()));
        for (std::size_t part = 0; part < record.parts.size(); ++part) {
            write_str(out, record.parts[part].name, what + " part " + std::to_string(part));
            out.push_back(record.parts[part].flag);
        }
    }
    put_u32(out, static_cast<std::uint32_t>(table.head_records.size()));
    for (std::size_t index = 0; index < table.head_records.size(); ++index) {
        write_str(out, table.head_records[index].stem, "head record " + std::to_string(index) + " stem");
        write_str(out, table.head_records[index].folder, "head record " + std::to_string(index) + " folder");
    }
    return out;
}

}  // namespace cdmw::compose::detail
