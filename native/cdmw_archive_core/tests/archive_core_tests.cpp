#include "cdmw_archive_core.h"
#include "archive_core_internal.hpp"

#include <chrono>
#include <iostream>

namespace {

namespace fs = std::filesystem;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void append_u16(std::vector<std::uint8_t>& out, std::uint16_t value) {
    out.push_back(static_cast<std::uint8_t>(value & 0xFFu));
    out.push_back(static_cast<std::uint8_t>((value >> 8) & 0xFFu));
}

void write_u32_at(std::vector<std::uint8_t>& out, size_t offset, std::uint32_t value) {
    require(offset <= out.size() && out.size() - offset >= 4, "test write is outside the buffer");
    for (int shift = 0; shift < 32; shift += 8) out[offset + shift / 8] = static_cast<std::uint8_t>((value >> shift) & 0xFFu);
}

void write_bytes(const fs::path& path, const std::vector<std::uint8_t>& bytes) {
    fs::create_directories(path.parent_path());
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    require(static_cast<bool>(stream), "could not create test file");
    stream.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

std::vector<std::uint8_t> make_pamt(std::uint32_t stored_size, std::uint32_t original_size, std::uint16_t flags) {
    std::vector<std::uint8_t> data;
    cdmw::archive::append_u32(data, 0);
    cdmw::archive::append_u32(data, 1);
    cdmw::archive::append_u32(data, 0);
    for (int index = 0; index < 3; ++index) cdmw::archive::append_u32(data, 0);
    cdmw::archive::append_u32(data, 0);
    const std::string filename = "file.txt";
    cdmw::archive::append_u32(data, static_cast<std::uint32_t>(5 + filename.size()));
    cdmw::archive::append_u32(data, 0xFFFFFFFFu);
    data.push_back(static_cast<std::uint8_t>(filename.size()));
    data.insert(data.end(), filename.begin(), filename.end());
    cdmw::archive::append_u32(data, 0);
    cdmw::archive::append_u32(data, 1);
    cdmw::archive::append_u32(data, 0);
    cdmw::archive::append_u32(data, 0);
    cdmw::archive::append_u32(data, stored_size);
    cdmw::archive::append_u32(data, original_size);
    append_u16(data, 0);
    append_u16(data, flags);
    return data;
}

void test_index_and_raw_decode(const fs::path& root) {
    const std::vector<std::uint8_t> payload = {'h', 'e', 'l', 'l', 'o'};
    write_bytes(root / "0.paz", payload);
    write_bytes(root / "0.pamt", make_pamt(5, 5, 0));
    const auto index = root / "index.bin";
    std::uint64_t count = 0;
    std::array<char, 512> error{};
    const auto status = cdmw_archive_build_index_utf8(
        root.u8string().c_str(),
        index.u8string().c_str(),
        &count,
        error.data(),
        error.size());
    require(status == CDMW_ARCHIVE_OK, std::string("index build failed: ") + error.data());
    require(count == 1, "index did not contain one entry");
    const auto index_bytes = cdmw::archive::read_binary(index, 1024 * 1024);
    require(index_bytes.size() >= 64 + cdmw::archive::kIndexRecordSize, "index is truncated");
    require(std::memcmp(index_bytes.data(), "CDMWALI1", 8) == 0, "index magic is wrong");
    require(cdmw::archive::read_u32(index_bytes, 8) == 1, "index version is wrong");

    size_t required = 0;
    std::array<char, 64> note{};
    require(cdmw_archive_decode_entry_utf8(
        "file.txt", (root / "0.paz").u8string().c_str(), 0, 5, 5, 0,
        nullptr, 0, &required, note.data(), note.size(), error.data(), error.size()) == CDMW_ARCHIVE_OK,
        "raw size query failed");
    require(required == payload.size(), "raw size query is wrong");
    std::vector<std::uint8_t> decoded(required);
    require(cdmw_archive_decode_entry_utf8(
        "file.txt", (root / "0.paz").u8string().c_str(), 0, 5, 5, 0,
        decoded.data(), decoded.size(), &required, note.data(), note.size(), error.data(), error.size()) == CDMW_ARCHIVE_OK,
        "raw decode failed");
    require(decoded == payload, "raw decode changed bytes");
}

void test_lz4_and_chacha(const fs::path& root) {
    const std::vector<std::uint8_t> plain = {'h', 'e', 'l', 'l', 'o'};
    const std::vector<std::uint8_t> compressed = {0x50, 'h', 'e', 'l', 'l', 'o'};
    write_bytes(root / "lz4.paz", compressed);
    std::array<char, 512> error{};
    std::array<char, 64> note{};
    size_t required = plain.size();
    std::vector<std::uint8_t> output(required);
    require(cdmw_archive_decode_entry_utf8(
        "file.txt", (root / "lz4.paz").u8string().c_str(), 0, compressed.size(), plain.size(), 2,
        output.data(), output.size(), &required, note.data(), note.size(), error.data(), error.size()) == CDMW_ARCHIVE_OK,
        std::string("LZ4 decode failed: ") + error.data());
    require(output == plain, "LZ4 output is wrong");
    require(std::string(note.data()) == "LZ4", "LZ4 note is wrong");

    const auto encrypted = cdmw::archive::crypt_chacha20_filename(plain, "file.txt");
    write_bytes(root / "encrypted.paz", encrypted);
    output.assign(plain.size(), 0);
    required = output.size();
    require(cdmw_archive_decode_entry_utf8(
        "file.txt", (root / "encrypted.paz").u8string().c_str(), 0, encrypted.size(), plain.size(), 3u << 4,
        output.data(), output.size(), &required, note.data(), note.size(), error.data(), error.size()) == CDMW_ARCHIVE_OK,
        std::string("ChaCha20 decode failed: ") + error.data());
    require(output == plain, "ChaCha20 output is wrong");
    require(std::string(note.data()) == "ChaCha20", "ChaCha20 note is wrong");
}

void test_partial_dds_pathc(const fs::path& root) {
    const std::string virtual_path = "texture/test.dds";
    require(cdmw::archive::calculate_pa_checksum("/" + virtual_path) == 0x54E11B82u, "PATHC checksum vector is wrong");
    std::vector<std::uint8_t> header(0x80, 0);
    std::memcpy(header.data(), "DDS ", 4);
    write_u32_at(header, 4, 124);
    write_u32_at(header, 12, 4);
    write_u32_at(header, 16, 4);
    write_u32_at(header, 20, 8);
    write_u32_at(header, 28, 1);
    write_u32_at(header, 32, 9);
    write_u32_at(header, 36, 8);
    write_u32_at(header, 76, 32);
    write_u32_at(header, 80, 4);
    std::memcpy(header.data() + 84, "DXT1", 4);

    std::vector<std::uint8_t> pathc;
    cdmw::archive::append_u32(pathc, 0);
    cdmw::archive::append_u32(pathc, 0);
    cdmw::archive::append_u32(pathc, 0x80);
    cdmw::archive::append_u32(pathc, 1);
    cdmw::archive::append_u32(pathc, 1);
    cdmw::archive::append_u32(pathc, 0);
    cdmw::archive::append_u32(pathc, 0);
    pathc.insert(pathc.end(), header.begin(), header.end());
    cdmw::archive::append_u32(pathc, cdmw::archive::calculate_pa_checksum("/" + virtual_path));
    append_u16(pathc, 0);
    pathc.push_back(0);
    pathc.push_back(0);
    pathc.insert(pathc.end(), 16, 0);

    std::vector<std::uint8_t> payload = header;
    payload.push_back(0x80);
    const std::array<std::uint8_t, 8> pixels = {1, 2, 3, 4, 5, 6, 7, 8};
    payload.insert(payload.end(), pixels.begin(), pixels.end());

    const auto pamt = root / "game" / "base" / "0.pamt";
    const auto paz = root / "game" / "base" / "0.paz";
    write_bytes(pamt, {});
    write_bytes(paz, payload);
    write_bytes(root / "game" / "meta" / "0.pathc", pathc);

    std::vector<std::uint8_t> output(0x80 + pixels.size(), 0);
    size_t required = output.size();
    std::array<char, 512> error{};
    std::array<char, 64> note{};
    require(cdmw_archive_decode_entry_with_context_utf8(
        virtual_path.c_str(), pamt.u8string().c_str(), paz.u8string().c_str(),
        0, payload.size(), output.size(), 1,
        output.data(), output.size(), &required, note.data(), note.size(), error.data(), error.size()) == CDMW_ARCHIVE_OK,
        std::string("partial DDS decode failed: ") + error.data());
    require(required == output.size(), "partial DDS size is wrong");
    require(std::memcmp(output.data(), "DDS ", 4) == 0, "partial DDS header is wrong");
    require(std::equal(pixels.begin(), pixels.end(), output.end() - pixels.size()), "partial DDS pixels are wrong");
    require(std::string(note.data()) == "PartialDDS+PATHC", "partial DDS note is wrong");
}

}  // namespace

int main() {
    const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const fs::path root = fs::temp_directory_path() / ("cdmw-archive-core-test-" + std::to_string(stamp));
    try {
        fs::create_directories(root);
        require(cdmw_archive_core_abi_version() == CDMW_ARCHIVE_CORE_ABI_VERSION, "ABI version is wrong");
        test_index_and_raw_decode(root / "raw");
        test_lz4_and_chacha(root / "codec");
        test_partial_dds_pathc(root / "partial-dds");
        fs::remove_all(root);
        std::cout << "cdmw archive core self-test: PASS\n";
        return 0;
    } catch (const std::exception& exception) {
        std::error_code error;
        fs::remove_all(root, error);
        std::cerr << "cdmw archive core self-test: FAIL: " << exception.what() << "\n";
        return 1;
    }
}
