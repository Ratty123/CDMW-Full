// archive_format.calculate_pa_checksum and hashlittle: lookup3 with two seeds.
#include "composer_internal.hpp"

namespace cdmw::compose {
namespace {

constexpr std::uint32_t rot(std::uint32_t value, int shift) { return (value << shift) | (value >> (32 - shift)); }

std::uint32_t word(const std::uint8_t* data) { return static_cast<std::uint32_t>(detail::le(data, 4)); }

std::uint32_t lookup3(const std::uint8_t* data, std::size_t size, std::uint32_t start) {
    std::uint32_t a = start, b = start, c = start;
    std::size_t remaining = size;
    for (; remaining > 12; remaining -= 12, data += 12) {
        a += word(data);
        b += word(data + 4);
        c += word(data + 8);
        a -= c; a ^= rot(c, 4); c += b;
        b -= a; b ^= rot(a, 6); a += c;
        c -= b; c ^= rot(b, 8); b += a;
        a -= c; a ^= rot(c, 16); c += b;
        b -= a; b ^= rot(a, 19); a += c;
        c -= b; c ^= rot(b, 4); b += a;
    }
    if (remaining == 0) return c;
    std::uint8_t tail[12] = {};
    for (std::size_t i = 0; i < remaining; ++i) tail[i] = data[i];
    a += word(tail);
    b += word(tail + 4);
    c += word(tail + 8);
    c ^= b; c -= rot(b, 14);
    a ^= c; a -= rot(c, 11);
    b ^= a; b -= rot(a, 25);
    c ^= b; c -= rot(b, 16);
    a ^= c; a -= rot(c, 4);
    b ^= a; b -= rot(a, 14);
    c ^= b; c -= rot(b, 24);
    return c;
}

}  // namespace

std::uint32_t pa_checksum(const std::uint8_t* data, std::size_t size) {
    return lookup3(data, size, static_cast<std::uint32_t>(size) + 0xDEBA1DCDu);
}

std::uint32_t hashlittle(const std::uint8_t* data, std::size_t size, std::uint32_t initial) {
    return lookup3(data, size, 0xDEADBEEFu + static_cast<std::uint32_t>(size) + initial);
}

}  // namespace cdmw::compose
