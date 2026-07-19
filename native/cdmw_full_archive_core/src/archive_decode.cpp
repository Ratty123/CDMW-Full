#include "archive_core_internal.hpp"

namespace cdmw::full_archive {

namespace {

std::uint32_t rotate_left(std::uint32_t value, int shift) {
    return static_cast<std::uint32_t>((value << shift) | (value >> (32 - shift)));
}

std::uint32_t read_u32_padded(const std::vector<std::uint8_t>& data, size_t offset) {
    std::uint32_t value = 0;
    for (size_t index = 0; index < 4; ++index) {
        if (offset + index < data.size()) value |= static_cast<std::uint32_t>(data[offset + index]) << (index * 8);
    }
    return value;
}

std::uint32_t lookup3_finalize(std::uint32_t a, std::uint32_t b, std::uint32_t c) {
    c = (c ^ b) - rotate_left(b, 14);
    a = (a ^ c) - rotate_left(c, 11);
    b = (b ^ a) - rotate_left(a, 25);
    c = (c ^ b) - rotate_left(b, 16);
    a = (a ^ c) - rotate_left(c, 4);
    b = (b ^ a) - rotate_left(a, 14);
    return (c ^ b) - rotate_left(b, 24);
}

std::uint32_t hashlittle(const std::vector<std::uint8_t>& data, std::uint32_t initial) {
    size_t remaining = data.size();
    std::uint32_t a = 0xDEADBEEFu + static_cast<std::uint32_t>(data.size()) + initial;
    std::uint32_t b = a;
    std::uint32_t c = a;
    size_t offset = 0;
    while (remaining > 12) {
        a += read_u32_padded(data, offset);
        b += read_u32_padded(data, offset + 4);
        c += read_u32_padded(data, offset + 8);
        a -= c; a ^= rotate_left(c, 4); c += b;
        b -= a; b ^= rotate_left(a, 6); a += c;
        c -= b; c ^= rotate_left(b, 8); b += a;
        a -= c; a ^= rotate_left(c, 16); c += b;
        b -= a; b ^= rotate_left(a, 19); a += c;
        c -= b; c ^= rotate_left(b, 4); b += a;
        offset += 12;
        remaining -= 12;
    }
    if (remaining >= 12) c += read_u32_padded(data, offset + 8);
    else if (remaining >= 9) c += read_u32_padded(data, offset + 8) & (0xFFFFFFFFu >> (8u * (12u - static_cast<unsigned>(remaining))));
    if (remaining >= 8) b += read_u32_padded(data, offset + 4);
    else if (remaining >= 5) b += read_u32_padded(data, offset + 4) & (0xFFFFFFFFu >> (8u * (8u - static_cast<unsigned>(remaining))));
    if (remaining >= 4) a += read_u32_padded(data, offset);
    else if (remaining >= 1) a += read_u32_padded(data, offset) & (0xFFFFFFFFu >> (8u * (4u - static_cast<unsigned>(remaining))));
    else return c;
    return lookup3_finalize(a, b, c);
}

void chacha_quarter_round(std::uint32_t& a, std::uint32_t& b, std::uint32_t& c, std::uint32_t& d) {
    a += b; d ^= a; d = rotate_left(d, 16);
    c += d; b ^= c; b = rotate_left(b, 12);
    a += b; d ^= a; d = rotate_left(d, 8);
    c += d; b ^= c; b = rotate_left(b, 7);
}

std::array<std::uint8_t, 64> chacha20_block(const std::array<std::uint32_t, 16>& state) {
    auto working = state;
    for (int round = 0; round < 10; ++round) {
        chacha_quarter_round(working[0], working[4], working[8], working[12]);
        chacha_quarter_round(working[1], working[5], working[9], working[13]);
        chacha_quarter_round(working[2], working[6], working[10], working[14]);
        chacha_quarter_round(working[3], working[7], working[11], working[15]);
        chacha_quarter_round(working[0], working[5], working[10], working[15]);
        chacha_quarter_round(working[1], working[6], working[11], working[12]);
        chacha_quarter_round(working[2], working[7], working[8], working[13]);
        chacha_quarter_round(working[3], working[4], working[9], working[14]);
    }
    std::array<std::uint8_t, 64> output{};
    for (size_t index = 0; index < working.size(); ++index) {
        working[index] += state[index];
        for (int byte = 0; byte < 4; ++byte) {
            output[index * 4 + byte] = static_cast<std::uint8_t>((working[index] >> (byte * 8)) & 0xFFu);
        }
    }
    return output;
}

std::vector<std::uint8_t> lz4_decompress(const std::vector<std::uint8_t>& input, size_t output_size) {
    if (output_size > kMaximumDecodedEntryBytes) throw std::runtime_error("decoded entry exceeds the one GiB resource limit");
    std::vector<std::uint8_t> output(output_size);
    size_t input_position = 0;
    size_t output_position = 0;
    while (input_position < input.size()) {
        const auto token = input[input_position++];
        size_t literal_length = token >> 4;
        if (literal_length == 15) {
            std::uint8_t value = 255;
            while (input_position < input.size() && value == 255) {
                value = input[input_position++];
                literal_length += value;
            }
        }
        if (literal_length > input.size() - input_position || literal_length > output.size() - output_position) {
            throw std::runtime_error("LZ4 literal run is outside its buffer");
        }
        std::copy_n(input.data() + input_position, literal_length, output.data() + output_position);
        input_position += literal_length;
        output_position += literal_length;
        if (input_position == input.size()) break;
        if (input.size() - input_position < 2) throw std::runtime_error("LZ4 match offset is truncated");
        const size_t match_offset = input[input_position] | (static_cast<size_t>(input[input_position + 1]) << 8);
        input_position += 2;
        if (match_offset == 0 || match_offset > output_position) throw std::runtime_error("LZ4 match offset is invalid");
        size_t match_length = token & 0x0Fu;
        if (match_length == 15) {
            std::uint8_t value = 255;
            while (input_position < input.size() && value == 255) {
                value = input[input_position++];
                match_length += value;
            }
        }
        match_length += 4;
        if (match_length > output.size() - output_position) throw std::runtime_error("LZ4 match run is outside its output buffer");
        for (size_t index = 0; index < match_length; ++index) {
            output[output_position + index] = output[output_position - match_offset + index];
        }
        output_position += match_length;
    }
    if (output_position != output.size()) throw std::runtime_error("LZ4 block decompressed to an unexpected size");
    return output;
}

std::vector<std::uint8_t> read_entry_raw(
    const fs::path& paz_path,
    std::uint64_t archive_offset,
    std::uint64_t stored_size) {
    if (stored_size > kMaximumDecodedEntryBytes) throw std::runtime_error("stored entry exceeds the one GiB resource limit");
    std::error_code error;
    const auto file_size = fs::file_size(paz_path, error);
    if (error) throw std::runtime_error("could not determine PAZ size: " + paz_path.string());
    if (archive_offset > file_size || stored_size > file_size - archive_offset) {
        throw std::runtime_error("archive entry range is outside the PAZ file");
    }
    std::ifstream stream(paz_path, std::ios::binary);
    if (!stream) throw std::runtime_error("could not open PAZ file: " + paz_path.string());
    stream.seekg(static_cast<std::streamoff>(archive_offset), std::ios::beg);
    std::vector<std::uint8_t> data(static_cast<size_t>(stored_size));
    if (!data.empty()) {
        stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
        if (static_cast<size_t>(stream.gcount()) != data.size()) throw std::runtime_error("short read from PAZ file");
    }
    return data;
}

std::vector<std::uint8_t> maybe_decompress_partial_par(
    const std::vector<std::uint8_t>& data,
    std::uint64_t original_size) {
    if (data.size() < 0x50 || std::memcmp(data.data(), "PAR ", 4) != 0) return {};
    struct Slot { std::uint32_t compressed; std::uint32_t decoded; size_t offset; };
    std::vector<Slot> slots;
    size_t source_offset = 0x50;
    size_t rebuilt_size = 0x50;
    bool saw_compressed = false;
    for (size_t index = 0; index < 8; ++index) {
        const size_t slot_offset = 0x10 + index * 8;
        const auto compressed = read_u32(data, slot_offset);
        const auto decoded = read_u32(data, slot_offset + 4);
        if (decoded == 0) continue;
        const auto chunk = compressed > 0 ? compressed : decoded;
        if (chunk > data.size() - source_offset || decoded > original_size - std::min<std::uint64_t>(original_size, rebuilt_size)) return {};
        slots.push_back({compressed, decoded, source_offset});
        source_offset += chunk;
        rebuilt_size += decoded;
        saw_compressed = saw_compressed || compressed > 0;
    }
    if (!saw_compressed || source_offset != data.size() || rebuilt_size != original_size) return {};
    std::vector<std::uint8_t> rebuilt(data.begin(), data.begin() + 0x50);
    for (const auto& slot : slots) {
        const size_t chunk_size = slot.compressed > 0 ? slot.compressed : slot.decoded;
        std::vector<std::uint8_t> chunk(data.begin() + slot.offset, data.begin() + slot.offset + chunk_size);
        if (slot.compressed > 0) chunk = lz4_decompress(chunk, slot.decoded);
        rebuilt.insert(rebuilt.end(), chunk.begin(), chunk.end());
    }
    for (size_t index = 0; index < 8; ++index) {
        const size_t slot_offset = 0x10 + index * 8;
        std::fill_n(rebuilt.begin() + slot_offset, size_t{4}, std::uint8_t{0});
    }
    return rebuilt;
}

}  // namespace

std::vector<std::uint8_t> crypt_chacha20_filename(
    const std::vector<std::uint8_t>& data,
    const std::string& filename) {
    const auto basename = lower_copy(basename_from_path(filename));
    const std::vector<std::uint8_t> basename_bytes(basename.begin(), basename.end());
    const std::uint32_t seed = hashlittle(basename_bytes, 0x000C5EDEu);
    const std::uint32_t key_base = seed ^ 0x60616263u;
    const std::array<std::uint32_t, 8> deltas = {
        0x00000000u, 0x0A0A0A0Au, 0x0C0C0C0Cu, 0x06060606u,
        0x0E0E0E0Eu, 0x0A0A0A0Au, 0x06060606u, 0x02020202u,
    };
    std::array<std::uint32_t, 16> state = {
        0x61707865u, 0x3320646Eu, 0x79622D32u, 0x6B206574u,
        key_base ^ deltas[0], key_base ^ deltas[1], key_base ^ deltas[2], key_base ^ deltas[3],
        key_base ^ deltas[4], key_base ^ deltas[5], key_base ^ deltas[6], key_base ^ deltas[7],
        seed, seed, seed, seed,
    };
    std::vector<std::uint8_t> output(data.size());
    for (size_t offset = 0; offset < data.size(); offset += 64) {
        const auto block = chacha20_block(state);
        const auto count = std::min<size_t>(64, data.size() - offset);
        for (size_t index = 0; index < count; ++index) output[offset + index] = data[offset + index] ^ block[index];
        if (++state[12] == 0) ++state[13];
    }
    return output;
}

DecodeResult decode_entry(
    const std::string& virtual_path,
    const fs::path& pamt_path,
    const fs::path& paz_path,
    std::uint64_t archive_offset,
    std::uint64_t stored_size,
    std::uint64_t original_size,
    std::uint32_t flags) {
    if (virtual_path.empty()) throw std::invalid_argument("virtual path must not be empty");
    if (original_size > kMaximumDecodedEntryBytes) throw std::runtime_error("decoded entry exceeds the one GiB resource limit");
    auto data = read_entry_raw(paz_path, archive_offset, stored_size);
    std::vector<std::string> notes;
    const auto encryption_type = (flags >> 4) & 0x0Fu;
    if ((flags >> 4) != 0) {
        if (encryption_type != 3) throw UnsupportedError("unsupported archive encryption type " + std::to_string(encryption_type));
        data = crypt_chacha20_filename(data, virtual_path);
        notes.emplace_back("ChaCha20");
    }
    if (stored_size != original_size) {
        const auto compression_type = flags & 0x0Fu;
        if (compression_type == 2) {
            data = lz4_decompress(data, static_cast<size_t>(original_size));
            notes.emplace_back("LZ4");
        } else if (compression_type == 1) {
            auto partial_par = maybe_decompress_partial_par(data, original_size);
            if (!partial_par.empty()) {
                data = std::move(partial_par);
                notes.emplace_back("PartialPAR");
            } else if (lower_copy(fs::path(virtual_path).extension().string()) == ".dds" && !pamt_path.empty()) {
                data = reconstruct_partial_dds(virtual_path, pamt_path, data, original_size);
                notes.emplace_back("PartialDDS+PATHC");
            } else {
                notes.emplace_back("PartialRaw");
            }
        } else {
            throw UnsupportedError("unsupported archive compression type " + std::to_string(compression_type));
        }
    }
    std::ostringstream note;
    for (size_t index = 0; index < notes.size(); ++index) {
        if (index > 0) note << ',';
        note << notes[index];
    }
    return {std::move(data), note.str()};
}

}  // namespace cdmw::full_archive
