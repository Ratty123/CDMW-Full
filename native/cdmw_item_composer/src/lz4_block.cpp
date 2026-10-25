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

// Accepts exactly the blocks liblz4's LZ4_decompress_safe accepts for a full-size decode:
// a sequence whose literals end within the last twelve output bytes must be the last one
// and end the input, matches stay inside the output and end before its last five bytes,
// and offset 0 copies zeros as the reference decoder does.
Bytes decompress(const std::uint8_t* data, std::size_t size, std::size_t output_size) {
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
    if (op != output_size) corrupt("it expands to a different size");
    return out;
}

Bytes compress(const std::uint8_t* data, std::size_t size) {
    Bytes out;
    out.reserve(size + size / 255 + 16);
    const auto emit_length = [&](std::size_t rest) {
        for (; rest >= 255; rest -= 255) out.push_back(255);
        out.push_back(static_cast<std::uint8_t>(rest));
    };
    const auto emit = [&](std::size_t anchor, std::size_t literals, std::size_t offset, std::size_t length) {
        const std::size_t code = length ? length - min_match : 0;
        out.push_back(static_cast<std::uint8_t>((std::min<std::size_t>(literals, 15) << 4) | std::min<std::size_t>(code, 15)));
        if (literals >= 15) emit_length(literals - 15);
        out.insert(out.end(), data + anchor, data + anchor + literals);
        if (!length) return;
        out.push_back(static_cast<std::uint8_t>(offset));
        out.push_back(static_cast<std::uint8_t>(offset >> 8));
        if (code >= 15) emit_length(code - 15);
    };
    const auto read32 = [&](std::size_t at) {
        std::uint32_t value;
        std::memcpy(&value, data + at, 4);
        return value;
    };
    std::size_t anchor = 0;
    if (size > match_start_limit) {
        std::vector<std::size_t> table(1u << 12, SIZE_MAX);
        const std::size_t last_start = size - match_start_limit, match_end = size - last_literals;
        for (std::size_t at = 0; at <= last_start;) {
            const auto sequence = read32(at);
            auto& slot = table[(sequence * 2654435761u) >> 20];
            const auto candidate = slot;
            slot = at;
            if (candidate == SIZE_MAX || at - candidate > max_offset || read32(candidate) != sequence) {
                ++at;
                continue;
            }
            std::size_t length = min_match;
            while (at + length < match_end && data[candidate + length] == data[at + length]) ++length;
            emit(anchor, at - anchor, at - candidate, length);
            at += length;
            anchor = at;
        }
    }
    emit(anchor, size - anchor, 0, 0);
    return out;
}

}  // namespace cdmw::compose::lz4
