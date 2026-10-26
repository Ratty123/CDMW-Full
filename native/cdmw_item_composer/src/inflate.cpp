// Raw DEFLATE (RFC 1951) decoding for ZIP members, refusing what zlib refuses:
// over-subscribed codes, incomplete codes other than a single one-bit code, mismatched
// stored-block lengths, symbols outside the tables and distances before the output.
#include "composer_internal.hpp"

namespace cdmw::compose {
namespace {

[[noreturn]] void invalid(const char* reason) { throw FormatError(std::string("invalid deflate stream: ") + reason); }

// The output reached its limit with more of the stream still to come.
struct LimitReached {};

class Bits {
public:
    Bits(const std::uint8_t* data, std::size_t size) : data_(data), size_(size) {}
    unsigned take(int count) {
        std::uint64_t value = buffer_;
        while (held_ < count) {
            if (at_ >= size_) invalid("the stream ends early");
            value |= std::uint64_t(data_[at_++]) << held_;
            held_ += 8;
        }
        buffer_ = value >> count;
        held_ -= count;
        return static_cast<unsigned>(value & ((std::uint64_t(1) << count) - 1));
    }
    void align() {
        buffer_ = 0;
        held_ = 0;
    }
    std::uint8_t byte() {
        if (at_ >= size_) invalid("a stored block ends early");
        return data_[at_++];
    }

private:
    const std::uint8_t* data_;
    std::size_t size_, at_ = 0;
    std::uint64_t buffer_ = 0;
    int held_ = 0;
};

constexpr int max_bits = 15;

struct Code {
    std::array<std::uint16_t, max_bits + 1> count{};
    std::vector<std::uint16_t> symbol;
};

enum class Kind { lengths, literals, distances };

// Canonical Huffman code from code lengths, with zlib's completeness rules.
Code build(const std::uint8_t* lengths, std::size_t n, Kind kind) {
    Code code;
    code.symbol.resize(n);
    for (std::size_t i = 0; i < n; ++i) ++code.count[lengths[i]];
    int max = 0;
    for (int bits = max_bits; bits >= 1; --bits)
        if (code.count[bits]) { max = bits; break; }
    if (max == 0) {
        // zlib accepts an empty distance code (no matches can follow) but not others.
        if (kind == Kind::distances) return code;
        invalid("a code has no symbols");
    }
    int left = 1;
    for (int bits = 1; bits <= max_bits; ++bits) {
        left <<= 1;
        left -= code.count[bits];
        if (left < 0) invalid("an over-subscribed code");
    }
    if (left > 0 && (kind == Kind::lengths || max != 1)) invalid("an incomplete code");
    std::array<std::uint16_t, max_bits + 2> offsets{};
    for (int bits = 1; bits <= max_bits; ++bits) offsets[bits + 1] = static_cast<std::uint16_t>(offsets[bits] + code.count[bits]);
    for (std::size_t i = 0; i < n; ++i)
        if (lengths[i]) code.symbol[offsets[lengths[i]]++] = static_cast<std::uint16_t>(i);
    code.count[0] = 0;
    return code;
}

int decode(Bits& bits, const Code& code) {
    int value = 0, first = 0, index = 0;
    for (int length = 1; length <= max_bits; ++length) {
        value |= static_cast<int>(bits.take(1));
        const int count = code.count[length];
        if (value - count < first) return code.symbol[static_cast<std::size_t>(index + (value - first))];
        index += count;
        first += count;
        first <<= 1;
        value <<= 1;
    }
    invalid("a code that is not in the table");
}

constexpr std::uint16_t length_base[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
                                           35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
constexpr std::uint8_t length_extra[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
constexpr std::uint16_t distance_base[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
                                             257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
constexpr std::uint8_t distance_extra[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

void codes(Bits& bits, Bytes& out, std::size_t limit, const Code& literals, const Code& distances, bool have_distances) {
    for (;;) {
        const int symbol = decode(bits, literals);
        if (symbol < 256) {
            if (out.size() >= limit) throw LimitReached{};
            out.push_back(static_cast<std::uint8_t>(symbol));
            continue;
        }
        if (symbol == 256) return;
        const int index = symbol - 257;
        if (index >= 29) invalid("a length symbol outside the table");
        const std::size_t length = length_base[index] + bits.take(length_extra[index]);
        if (!have_distances) invalid("a match with no distance code");
        const int code = decode(bits, distances);
        if (code >= 30) invalid("a distance symbol outside the table");
        const std::size_t distance = distance_base[code] + bits.take(distance_extra[code]);
        if (distance > out.size()) invalid("a distance before the start of the output");
        for (std::size_t i = 0; i < length; ++i) {
            if (out.size() >= limit) throw LimitReached{};
            out.push_back(out[out.size() - distance]);
        }
    }
}

}  // namespace

namespace detail {

Inflated inflate_prefix(const std::uint8_t* data, std::size_t size, std::size_t limit) {
    Bits bits(data, size);
    Inflated result;
    auto& out = result.bytes;
    out.reserve(limit);
    static const auto fixed = [] {
        std::array<std::uint8_t, 288> lengths{};
        for (int i = 0; i < 144; ++i) lengths[i] = 8;
        for (int i = 144; i < 256; ++i) lengths[i] = 9;
        for (int i = 256; i < 280; ++i) lengths[i] = 7;
        for (int i = 280; i < 288; ++i) lengths[i] = 8;
        // All 32 five-bit codes, as zlib builds them; 30 and 31 are refused when decoded.
        std::array<std::uint8_t, 32> distances{};
        distances.fill(5);
        return std::make_pair(build(lengths.data(), lengths.size(), Kind::literals), build(distances.data(), distances.size(), Kind::distances));
    }();
    bool last = false;
    try {
    while (!last) {
        last = bits.take(1) != 0;
        const auto type = bits.take(2);
        if (type == 0) {
            bits.align();
            const unsigned length = bits.byte() | (bits.byte() << 8);
            const unsigned complement = bits.byte() | (bits.byte() << 8);
            if (length != (~complement & 0xFFFFu)) invalid("a stored block whose length and complement differ");
            for (unsigned i = 0; i < length; ++i) {
                if (out.size() >= limit) throw LimitReached{};
                out.push_back(bits.byte());
            }
        } else if (type == 1) {
            codes(bits, out, limit, fixed.first, fixed.second, true);
        } else if (type == 2) {
            const unsigned literal_count = bits.take(5) + 257, distance_count = bits.take(5) + 1, length_count = bits.take(4) + 4;
            if (literal_count > 286 || distance_count > 30) invalid("too many length or distance symbols");
            static constexpr std::uint8_t order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
            std::array<std::uint8_t, 19> code_lengths{};
            for (unsigned i = 0; i < length_count; ++i) code_lengths[order[i]] = static_cast<std::uint8_t>(bits.take(3));
            const auto lengths_code = build(code_lengths.data(), code_lengths.size(), Kind::lengths);
            std::array<std::uint8_t, 316> lengths{};
            for (unsigned i = 0; i < literal_count + distance_count;) {
                const int symbol = decode(bits, lengths_code);
                if (symbol < 16) {
                    lengths[i++] = static_cast<std::uint8_t>(symbol);
                    continue;
                }
                std::uint8_t value = 0;
                unsigned repeat;
                if (symbol == 16) {
                    if (i == 0) invalid("a repeat with no previous length");
                    value = lengths[i - 1];
                    repeat = 3 + bits.take(2);
                } else if (symbol == 17) {
                    repeat = 3 + bits.take(3);
                } else {
                    repeat = 11 + bits.take(7);
                }
                if (i + repeat > literal_count + distance_count) invalid("repeated lengths past the end");
                while (repeat--) lengths[i++] = value;
            }
            if (lengths[256] == 0) invalid("no end-of-block code");
            const auto literals = build(lengths.data(), literal_count, Kind::literals);
            const bool any_distance = std::any_of(lengths.begin() + literal_count, lengths.begin() + literal_count + distance_count, [](std::uint8_t v) { return v != 0; });
            const auto distances = build(lengths.data() + literal_count, distance_count, Kind::distances);
            codes(bits, out, limit, literals, distances, any_distance);
        } else {
            invalid("a reserved block type");
        }
    }
    } catch (const LimitReached&) {
        return result;
    } catch (const FormatError&) {
        // zipfile stops reading at the directory size, so a stream that has produced it
        // need not be finished there.
        if (out.size() == limit) return result;
        throw;
    }
    result.complete = true;
    return result;
}

}  // namespace detail

Bytes inflate(const std::uint8_t* data, std::size_t size, std::size_t limit) {
    auto result = detail::inflate_prefix(data, size, limit);
    if (!result.complete) invalid("the output does not fit its limit, or the stream is unfinished");
    return std::move(result.bytes);
}

}  // namespace cdmw::compose
