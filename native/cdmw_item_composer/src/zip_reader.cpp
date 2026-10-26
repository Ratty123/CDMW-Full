// ZIP reading as Python's zipfile does it for .cditem packages: the end record search,
// prepended data, ZipInfo's name sanitizing and Unicode path fields, matching local
// header names, overlap checks and CRC. ZIP64 and cp437 names outside ASCII refuse as
// Unsupported; packages use neither.
#include "composer_internal.hpp"

namespace cdmw::compose {
using namespace detail;
namespace {

constexpr std::size_t end_record = 22, central_record = 46, local_record = 30;
constexpr std::size_t max_comment = 0xFFFF;

[[noreturn]] void bad(const std::string& reason) { throw FormatError("Bad zip file: " + reason); }

std::uint32_t crc_table_entry(std::uint32_t value) {
    for (int bit = 0; bit < 8; ++bit) value = value & 1 ? 0xEDB88320u ^ (value >> 1) : value >> 1;
    return value;
}

std::string decode_name(const Bytes& raw, bool utf8) {
    if (utf8) {
        if (!valid_utf8(raw)) bad("a file name is not UTF-8");
    } else if (std::any_of(raw.begin(), raw.end(), [](std::uint8_t c) { return c >= 0x80; })) {
        throw Unsupported("cp437 file names outside ASCII are not read");
    }
    return text_of(raw);
}

// ZipInfo's _sanitize_filename on Windows: end at NUL, backslashes become slashes.
std::string sanitize(std::string name) {
    if (const auto nul = name.find('\0'); nul != std::string::npos) name.resize(nul);
    return replace_all(std::move(name), "\\", "/");
}

}  // namespace

std::uint32_t crc32(const std::uint8_t* data, std::size_t size) {
    static const auto table = [] {
        std::array<std::uint32_t, 256> values{};
        for (std::uint32_t i = 0; i < 256; ++i) values[i] = crc_table_entry(i);
        return values;
    }();
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < size; ++i) crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFu;
}

ZipArchive::ZipArchive(Bytes data) : data_(std::move(data)) {
    // _EndRecData: the record at the very end with no comment, else the last signature in
    // the final 64 KiB plus the record.
    const auto size = data_.size();
    std::optional<std::size_t> record;
    if (size >= end_record && starts_with(slice(data_, size - end_record, size), "PK\x05\x06") &&
        data_[size - 2] == 0 && data_[size - 1] == 0) {
        record = size - end_record;
    } else {
        const std::size_t from = size > max_comment + end_record ? size - max_comment - end_record : 0;
        const std::string_view signature("PK\x05\x06", 4);
        for (std::size_t at = size >= 4 ? size - 4 + 1 : 0; at-- > from;) {
            if (std::equal(signature.begin(), signature.end(), data_.begin() + static_cast<std::ptrdiff_t>(at),
                           [](char a, std::uint8_t b) { return same_byte(a, b); })) {
                if (at + end_record > size) bad("File is not a zip file");
                record = at;
                break;
            }
        }
    }
    if (!record) bad("File is not a zip file");
    if (*record >= 20 && starts_with(slice(data_, *record - 20, *record - 16), "PK\x06\x07")) throw Unsupported("ZIP64 archives are not read");
    const std::uint64_t size_cd = u32(data_, *record + 12), offset_cd = u32(data_, *record + 16);
    const auto concat = static_cast<std::int64_t>(*record) - static_cast<std::int64_t>(size_cd) - static_cast<std::int64_t>(offset_cd);
    const auto start_dir = static_cast<std::int64_t>(offset_cd) + concat;
    if (start_dir < 0) bad("Bad offset for central directory");
    const auto directory = slice(data_, static_cast<std::size_t>(start_dir), static_cast<std::size_t>(start_dir + static_cast<std::int64_t>(size_cd)));
    std::size_t at = 0;
    std::uint64_t total = 0;
    while (total < size_cd) {
        if (at + central_record > directory.size()) bad("Truncated central directory");
        if (!starts_with(slice(directory, at, at + 4), "PK\x01\x02")) bad("Bad magic number for central directory");
        ZipMember member;
        const std::size_t name_length = u16(directory, at + 28), extra_length = u16(directory, at + 30), comment_length = u16(directory, at + 32);
        member.flags = u16(directory, at + 8);
        member.method = u16(directory, at + 10);
        member.crc = u32(directory, at + 16);
        member.compressed_size = u32(directory, at + 20);
        member.size = u32(directory, at + 24);
        member.external_attr = u32(directory, at + 38);
        member.header_offset = u32(directory, at + 42);
        const auto extract_version = directory[at + 6];
        auto cursor = at + central_record;
        const auto raw_name = slice(directory, cursor, cursor + name_length);
        cursor += name_length;
        member.orig_name = decode_name(raw_name, member.flags & 0x800);
        member.name = sanitize(member.orig_name);
        auto extra = slice(directory, cursor, cursor + extra_length);
        cursor += extra_length + comment_length;
        if (extract_version > 63) bad("zip file version " + std::to_string(extract_version / 10) + "." + std::to_string(extract_version % 10));
        // _decodeExtra
        for (std::size_t e = 0; extra.size() >= e + 4;) {
            const std::size_t type = u16(extra, e), length = u16(extra, e + 2);
            if (e + 4 + length > extra.size()) bad("Corrupt extra field");
            if (type == 0x0001 && (member.size == 0xFFFFFFFFu || member.compressed_size == 0xFFFFFFFFu || member.header_offset == 0xFFFFFFFFu))
                throw Unsupported("ZIP64 members are not read");
            if (type == 0x7075) {
                const auto field = slice(extra, e + 4, e + 4 + length);
                if (field.size() < 5) bad("Corrupt unicode path extra field (0x7075)");
                if (field[0] == 1 && u32(field, 1) == crc32(raw_name.data(), raw_name.size())) {
                    const auto unicode = slice(field, 5, field.size());
                    if (!valid_utf8(unicode)) bad("Corrupt unicode path extra field (0x7075): invalid utf-8 bytes");
                    if (!unicode.empty()) member.name = sanitize(text_of(unicode));
                }
            }
            e += 4 + length;
        }
        member.header_offset += concat;
        members_.push_back(std::move(member));
        total += central_record + name_length + extra_length + comment_length;
        at = cursor;
    }
    // Each member's data must end before the next local header (sorted, stable, reversed).
    std::vector<std::size_t> order(members_.size());
    for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](std::size_t x, std::size_t y) { return members_[x].header_offset < members_[y].header_offset; });
    std::int64_t end = start_dir;
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        members_[*it].end_offset = end;
        end = members_[*it].header_offset;
    }
}

Bytes ZipArchive::read(const ZipMember& member) const {
    if (member.header_offset < 0) bad("negative seek value");
    const auto at = static_cast<std::size_t>(std::min<std::uint64_t>(static_cast<std::uint64_t>(member.header_offset), data_.size()));
    if (at + local_record > data_.size()) bad("Truncated file header");
    if (!starts_with(slice(data_, at, at + 4), "PK\x03\x04")) bad("Bad magic number for file header");
    const std::size_t name_length = u16(data_, at + 26), extra_length = u16(data_, at + 28);
    const auto local_flags = u16(data_, at + 6);
    const auto name = slice(data_, at + local_record, at + local_record + name_length);
    if (member.flags & 0x20) bad("compressed patched data (flag bit 5)");
    if (member.flags & 0x40) bad("strong encryption (flag bit 6)");
    if (decode_name(name, local_flags & 0x800) != member.orig_name) bad("File name in directory and header differ.");
    const std::uint64_t start = std::uint64_t(at) + local_record + name_length + extra_length;
    if (static_cast<std::int64_t>(start + member.compressed_size) > member.end_offset && member.end_offset != member.header_offset)
        bad("Overlapped entries (possible zip bomb)");
    if (member.flags & 1) bad("the member is encrypted");
    if (member.method != 0 && member.method != 8) {
        if (member.method == 12 || member.method == 14 || member.method == 93) throw Unsupported("bzip2, LZMA and Zstandard members are not read");
        bad("That compression method is not supported");
    }
    const auto first = static_cast<std::size_t>(std::min<std::uint64_t>(start, data_.size()));
    const auto last = static_cast<std::size_t>(std::min<std::uint64_t>(start + member.compressed_size, data_.size()));
    if (member.compressed_size && first == last) bad("the member's data is missing");
    Bytes out;
    if (member.method == 0) {
        out.assign(data_.begin() + static_cast<std::ptrdiff_t>(first), data_.begin() + static_cast<std::ptrdiff_t>(last));
    } else {
        // zipfile truncates at the directory size and stops there; whether zlib would have
        // flagged what follows depends on its internal state, so such members refuse.
        auto inflated = inflate_prefix(data_.data() + first, last - first, static_cast<std::size_t>(member.size));
        if (!inflated.complete) throw Unsupported("a member whose stream runs past its directory size or ends unfinished");
        out = std::move(inflated.bytes);
    }
    if (crc32(out.data(), out.size()) != member.crc) bad("Bad CRC-32 for file " + member.name);
    if (out.size() != member.size) bad("the member's size differs from its directory size");
    return out;
}

}  // namespace cdmw::compose
