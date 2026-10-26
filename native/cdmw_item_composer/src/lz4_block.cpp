// Raw LZ4 blocks, as python-lz4's lz4.block.decompress(uncompressed_size=...) and
// lz4.block.compress(store_size=False) use them for the .paloc container.
#include "composer_internal.hpp"

#include <cstring>

namespace cdmw::compose::lz4 {
namespace {
constexpr std::size_t min_match = 4;
constexpr std::size_t last_literals = 5;  // the last five bytes are always literals
constexpr std::size_t match_start_limit = 12;  // no match starts in the last twelve bytes
constexpr std::size_t max_offset = 65535;

[[noreturn]] void corrupt(const char* reason) { throw FormatError(std::string("LZ4 block is invalid: ") + reason); }

std::size_t extended(const std::uint8_t* data, std::size_t size, std::size_t& at, std::size_t length) {
    std::uint8_t value = 255;
    while (value == 255) {
        if (at >= size) corrupt("a length runs past the block");
        value = data[at++];
        length += value;
    }
    return length;
}
}  // namespace

// Accepts exactly the blocks liblz4's LZ4_decompress_safe accepts into `output_size`
// bytes of room: a sequence whose literals end within the last twelve bytes of room must
// be the last one and end the input, matches stay inside the output and end before the
// last five bytes of room, and offset 0 copies zeros as the reference decoder does.
Bytes decompress_upto(const std::uint8_t* data, std::size_t size, std::size_t output_size) {
    Bytes out(output_size);
    if (output_size == 0) {
        if (size == 1 && data[0] == 0) return out;
        corrupt("an empty output needs a single zero token");
    }
    if (size == 0) corrupt("the block is empty");
    std::size_t in = 0, op = 0;
    for (;;) {
        if (in >= size) corrupt("the block ends inside a sequence");
        const auto token = data[in++];
        std::size_t literals = token >> 4;
        if (literals == 15) literals = extended(data, size, in, literals);
        if (literals > size - in || literals > output_size - op) corrupt("literals run past a buffer");
        std::memcpy(out.data() + op, data + in, literals);
        in += literals;
        op += literals;
        if (in == size) break;
        if (op + match_start_limit > output_size) corrupt("a match starts within the last twelve bytes");
        if (size - in < 2) corrupt("a match offset is truncated");
        const std::size_t offset = data[in] | (static_cast<std::size_t>(data[in + 1]) << 8);
        in += 2;
        if (offset > op) corrupt("a match offset points before the output");
        std::size_t length = token & 15u;
        if (length == 15) length = extended(data, size, in, length);
        length += min_match;
        if (length > output_size - op || op + length + last_literals > output_size) corrupt("a match runs into the last five bytes");
        if (offset == 0) {
            std::memset(out.data() + op, 0, length);
        } else {
            for (std::size_t i = 0; i < length; ++i) out[op + i] = out[op + i - offset];
        }
        op += length;
    }
    out.resize(op);
    return out;
}

Bytes decompress(const std::uint8_t* data, std::size_t size, std::size_t output_size) {
    auto out = decompress_upto(data, size, output_size);
    if (out.size() != output_size) corrupt("it expands to a different size");
    return out;
}

// liblz4 1.9.4's block compressor at acceleration 1, step for step, so blocks match
// python-lz4's lz4.block.compress byte for byte. python-lz4 compresses every size the way
// liblz4 does with a 32-bit position table: a 12-bit table indexed by the 5-byte hash, with
// a 64 KiB distance limit (measured: the 16-bit small-input table never matches it).
Bytes compress(const std::uint8_t* data, std::size_t size) {
    if (size == 0) return Bytes{0};
    if (size > 0x7E000000) throw FormatError("LZ4 input exceeds the block size limit");
    constexpr std::size_t min_length = match_start_limit + 1;
    constexpr int skip_trigger = 6;
    const auto read32 = [&](std::size_t at) { return static_cast<std::uint32_t>(detail::le(data + at, 4)); };
    const auto hash = [&](std::size_t at) {
        return static_cast<std::uint32_t>(((detail::le(data + at, 8) << 24) * 889523592379ull) >> (64 - 12));
    };
    std::vector<std::uint32_t> table(std::size_t(1) << 12, 0);
    const auto put = [&](std::uint32_t slot, std::size_t position) { table[slot] = static_cast<std::uint32_t>(position); };
    Bytes out;
    out.reserve(size + size / 255 + 16);
    const auto run = [&](std::size_t length) {
        for (; length >= 255; length -= 255) out.push_back(255);
        out.push_back(static_cast<std::uint8_t>(length));
    };
    const std::size_t mflimit_plus_one = size - match_start_limit + 1, match_limit = size - last_literals;
    std::size_t ip = 0, anchor = 0;
    if (size >= min_length) {
        put(hash(0), 0);
        ip = 1;
        auto forward_hash = hash(ip);
        for (;;) {
            std::size_t match = 0;
            // Find a match, skipping faster the longer none is found.
            std::size_t forward = ip;
            int step = 1, searches = 1 << skip_trigger;
            bool found = false;
            for (;;) {
                const auto slot = forward_hash;
                const auto current = forward;
                const std::size_t candidate = table[slot];
                ip = forward;
                forward += static_cast<std::size_t>(step);
                step = searches++ >> skip_trigger;
                if (forward > mflimit_plus_one) break;
                match = candidate;
                forward_hash = hash(forward);
                put(slot, current);
                if (candidate + max_offset < current) continue;
                if (read32(match) == read32(ip)) {
                    found = true;
                    break;
                }
            }
            if (!found) break;
            while (ip > anchor && match > 0 && data[ip - 1] == data[match - 1]) {
                --ip;
                --match;
            }
            auto token = out.size();
            out.push_back(0);
            const auto literals = ip - anchor;
            out[token] = static_cast<std::uint8_t>(std::min<std::size_t>(literals, 15) << 4);
            if (literals >= 15) run(literals - 15);
            out.insert(out.end(), data + anchor, data + ip);
            for (;;) {
                const auto offset = ip - match;
                out.push_back(static_cast<std::uint8_t>(offset));
                out.push_back(static_cast<std::uint8_t>(offset >> 8));
                std::size_t length = 0;
                while (ip + min_match + length < match_limit && data[ip + min_match + length] == data[match + min_match + length]) ++length;
                ip += length + min_match;
                out[token] = static_cast<std::uint8_t>(out[token] + std::min<std::size_t>(length, 15));
                if (length >= 15) run(length - 15);
                anchor = ip;
                if (ip >= mflimit_plus_one) break;
                put(hash(ip - 2), ip - 2);
                // An immediate match continues without literals.
                const auto slot = hash(ip);
                const std::size_t candidate = table[slot];
                put(slot, ip);
                if (candidate + max_offset >= ip && read32(candidate) == read32(ip)) {
                    match = candidate;
                    token = out.size();
                    out.push_back(0);
                    continue;
                }
                break;
            }
            if (ip >= mflimit_plus_one) break;
            forward_hash = hash(++ip);
        }
    }
    const auto literals = size - anchor;
    out.push_back(static_cast<std::uint8_t>(std::min<std::size_t>(literals, 15) << 4));
    if (literals >= 15) run(literals - 15);
    out.insert(out.end(), data + anchor, data + size);
    return out;
}

}  // namespace cdmw::compose::lz4
